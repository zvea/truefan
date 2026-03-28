# TrueFan Design

TrueFan is a fan control daemon for TrueNAS SCALE systems based on Supermicro X11 motherboards. It reads temperatures from IPMI, SMART, NVMe, and lm-sensors, then adjusts fan duty cycles via IPMI to keep things cool with minimal noise.

## Goals

- **Minimize noise** while staying within safe thermal limits.
- **Auto-detect** sensors and fans. Classify by class (cpu, drive, nvme, ambient) and apply sensible default curves.
- **Read multiple sensor backends** — IPMI for board-level sensors, SMART for SATA/SAS drives, `nvme-cli` for NVMe, lm-sensors for the rest. Auto-detected based on what's available.
- **Self-calibrate** how slow each fan can go without stalling, adapting as fans age or collect dust.
- **Fail safe** — go to 100% on crash, total sensor class failure, or stalled fan.
- **Keep a single config file** for user settings and daemon-learned state. Comments and formatting survive when the daemon writes back to it.
- **Expose per-fan target RPM** to Netdata over statsd (actual RPM already available via IPMI).

## Non-goals

- **GUI or web interface.** Config is a TOML file; monitoring is Netdata.
- **Multi-platform support.** Built for Supermicro X11 on TrueNAS SCALE. Might work elsewhere, but that's not a design constraint.
- **PID or advanced control theory.** Linear interpolation with max-demand-wins. PID can come later if needed.
- **Built-in alerting.** Stall recovery and setpoint changes show up as Netdata metrics. Alerting is Netdata's job.

## Architecture

### Process model

A small **watchdog parent** spawns the daemon as a child. If the child dies unexpectedly, the parent sets all fans to 100% and restarts it. On SIGTERM, the parent forwards the signal; the child restores IPMI to automatic fan control and exits; the parent follows.

### Main loop

Runs every `poll_interval_seconds` (default 5):

1. Read all sensors from every available backend.
2. Compute each sensor's demanded duty via its class's interpolation curve.
3. For each fan zone, take the max demand across all sensors mapped to it.
4. Pick the lowest setpoint that meets or exceeds the demand, considering all fans in the zone.
5. Apply via IPMI (only if changed since last cycle).
6. Read fan RPMs. On stall: set zone to 100%, try to restart, remove the lowest setpoint for that fan, persist to config.
7. Push per-fan target RPM to Netdata via statsd.

### Sensor backends

Each backend scans for available sensors and returns readings (name, class, temperature in °C) every poll cycle. Hardware changes (e.g. a drive added or removed) are picked up in the next poll — no config change or restart needed.

- **IPMI** — CPU, ambient, chipset via `pyghmi`.
- **SMART** — SATA/SAS drive temps via `pySMART` or `smartctl`.
- **NVMe** — NVMe temps via `nvme smart-log`.
- **lm-sensors** — everything else the kernel exposes, via `sensors -j`.

Each sensor is classified into a **sensor class** (cpu, ambient, drive, nvme). Curves are per class, not per individual sensor.

### Fan control

The daemon enables IPMI full manual fan mode on startup and restores automatic mode on exit. Duty cycles are set via Supermicro-specific IPMI raw commands. The X11SCA-F has two fan zones: **cpu** and **peripheral**. A zone can have multiple fans — duty is set per zone, but each fan has its own RPM sensor. Stall detection and setpoint tracking are per fan. A zone's effective minimum duty is determined by whichever fan in the zone has the highest minimum setpoint.

### Control algorithm

Each sensor class has an interpolation curve: `temp_low`, `temp_high`, `duty_low`, `duty_high`. Between the two temps, duty is linearly interpolated. Below `temp_low` → `duty_low`. Above `temp_high` → `duty_high` (typically 100%). The resulting duty is then snapped up to the nearest available setpoint for the fan.

Each curve feeds one or more fan zones. Per zone, the highest demand wins.

Default class-to-zone mapping:

| Sensor class | Fan zones |
|---|---|
| cpu | cpu, peripheral |
| ambient | peripheral |
| drive | peripheral |
| nvme | peripheral |

### Calibration

`truefan init` steps through duty levels for each fan, recording the RPM at each step. This builds a setpoint table (duty % → expected RPM) per fan. The lowest duty that kept the fan spinning becomes the minimum setpoint, rounded up to the nearest 5%. `truefan calibrate` re-runs this on an existing config (e.g. after cleaning or replacing fans).

During normal operation, if a fan stalls above its lowest setpoint, the daemon kicks the zone to 100%, removes that setpoint (raising the effective minimum), and saves the updated config.

### Configuration

Single TOML file via `tomlkit` — comments and formatting survive reads and writes. Has both user settings and daemon-managed state (setpoints, which you can also edit by hand). The daemon reloads the config on SIGHUP.

```toml
# Send SIGHUP to the daemon to reload this file.
poll_interval_seconds = 5

# Curves map sensor temps to fan duty cycles, one per sensor class.
# Defaults are built in — add a section here to override. Example:
#
# [curves.<class>]
# temp_low = 35      # °C — below this, fans run at duty_low
# temp_high = 80     # °C — above this, fans run at duty_high
# duty_low = 25      # % — minimum demanded duty (snapped up to nearest setpoint)
# duty_high = 100    # % — maximum demanded duty
# fan_zones = ["cpu", "peripheral"]

[curves.drive]
temp_low = 30
temp_high = 45
duty_low = 25
duty_high = 100
fan_zones = ["peripheral"]

# Learned via calibration — duty % = expected RPM.
# The daemon also removes the lowest setpoint on stall.
# You can edit these by hand too.
[fans.FAN1]
zone = "cpu"

[fans.FAN1.setpoints]  # duty % = expected RPM
25 = 320
30 = 450
40 = 620
50 = 780
100 = 1500

[fans.FAN2]
zone = "peripheral"

[fans.FAN2.setpoints]  # duty % = expected RPM
20 = 280
30 = 420
40 = 590
50 = 750
100 = 1450
```

### Module structure

```
truefan/
    __init__.py
    main.py          # entry point, argument parsing (init / run / calibrate)
    watchdog.py      # parent process — spawn, monitor, failsafe
    daemon.py        # main poll loop
    config.py        # load/save TOML, config dataclasses
    control.py       # interpolation math, max-demand-wins logic
    fans.py          # fan duty commands, RPM reads, zone control via pyghmi
    sensors/
        __init__.py  # common SensorReading type, backend interface
        ipmi.py      # IPMI temp sensors
        smart.py     # SATA/SAS via smartctl/pySMART
        nvme.py      # NVMe via nvme-cli
        lmsensors.py # lm-sensors via sensors -j
    calibrate.py     # ramp-down test + stall detection/recovery
    metrics.py       # statsd UDP push to Netdata
```

### Observability

Per-fan target RPM goes to Netdata's statsd listener over UDP (e.g. `truefan.fan.FAN1.target_rpm:620|g`). The target RPM is the expected RPM from the fan's setpoint table at the current duty. Netdata already has actual RPM via IPMI — comparing the two reveals anomalies. The daemon itself just logs to stderr — fan speed changes, sensor errors, stall events.

### Failsafe

- **Crash:** watchdog sets all fans to 100%, restarts the daemon.
- **Sensor failure:** a single failed sensor is ignored (logged as a warning); the remaining sensors in its class still drive the curve. If *all* sensors in a class fail, the affected zones go to 100%.
- **Stall:** zone goes to 100%, recovery attempted, lowest setpoint removed and config saved.
- **Clean shutdown:** IPMI restored to automatic fan control.

## CLI

- **`truefan init [--config PATH]`** — detect fans, run calibration (build setpoint tables), write a config with calibrated values and one example curve section. Refuses if the config already exists.
- **`truefan run [--config PATH]`** — start the daemon (wrapped by the watchdog). Refuses if no config exists, pointing you to `truefan init`.
- **`truefan calibrate [--config PATH]`** — re-run calibration on an existing config. Rebuilds setpoint tables in place and exits.

Default config path: `truefan.toml` next to the script. `--config` overrides.
