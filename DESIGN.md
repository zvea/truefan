# TrueFan Design

TrueFan is a fan control daemon for TrueNAS SCALE systems based on Supermicro X11 motherboards. It reads temperatures from IPMI, SMART, NVMe, and lm-sensors, then adjusts fan duty cycles via IPMI to keep things cool with minimal noise.

## Goals

- **Minimize noise** while staying within safe thermal limits.
- **Auto-detect** sensors and fans. Classify by class (cpu, drive, nvme, ambient, other) and apply sensible default curves. Use hardware-reported thermal limits when available.
- **Read multiple sensor backends** — IPMI for board-level sensors, SMART for SATA/SAS drives, `nvme-cli` for NVMe, lm-sensors for the rest. Auto-detected based on what's available.
- **Self-calibrate** how slow each fan can go without stalling, can be recalibrated as fans age or collect dust.
- **Fail safe** — go to 100% on crash, total sensor class failure, or stalled fan.
- **Keep a single config file** for user settings and daemon-learned state. Comments and formatting survive when the daemon writes back to it.
- **Expose metrics** to Netdata over statsd — per-sensor thermal load, per-zone duty, per-fan target RPM, and daemon restart count.

## Non-goals

- **GUI or web interface.** Config is a TOML file; monitoring is Netdata.
- **Multi-platform support.** Built for Supermicro X11 on TrueNAS SCALE. Might work elsewhere, but that's not a design constraint.
- **PID or advanced control theory.** Linear interpolation with max-demand-wins. PID can come later if needed.
- **Built-in alerting.** Stall recovery and setpoint changes show up as Netdata metrics. Alerting is Netdata's job.

## Architecture

### Process model

A small **watchdog parent** spawns the daemon as a child. If the child dies unexpectedly, the parent sets all fans to 100% and restarts it. On SIGTERM, the parent forwards the signal; the child sets fans to full speed and exits; the parent follows.

A PID file (`/var/run/truefan.pid`) with OS-level `flock` prevents multiple instances. `truefan run` acquires the lock before starting the watchdog; the lock is released automatically on process exit (including `kill -9`). `truefan init` and `truefan recalibrate` acquire the lock for the duration of their work, preventing conflicts with a running daemon or each other. `truefan sensors` is read-only and skips the check.

### Main loop

Runs every `poll_interval_seconds` (default 15):

1. Read all sensors from every available backend.
2. Compute each sensor's demanded duty via its class's interpolation curve.
3. For each fan zone, take the max demand across all sensors mapped to it.
4. Snap to the nearest setpoint, considering all fans in the zone.
5. Apply spindown window: the actual duty is the max of all duties computed in the last `spindown_window_seconds` (default 180). Spin-up is instant; spin-down waits for the window to clear.
6. Apply via IPMI (only if changed since last cycle).
7. Read fan RPMs. On stall: set zone to 100%, try to restart, remove the lowest setpoint for that fan, persist to config.
8. Push metrics to Netdata via statsd (thermal load, zone duty, target RPM).

### Sensor backends

Each backend scans for available sensors and returns readings every poll cycle. Each reading has a unique id (`<backend>-<device-path>` with spaces replaced by underscores, e.g. `smart-sda`, `lmsensors-coretemp-isa-0000-Core_0`), a sensor class, a temperature, and optional hardware-reported thresholds (`temp_max`, `temp_crit`). Hardware changes (e.g. a drive added or removed) are picked up in the next poll — no config change or restart needed.

- **IPMI** — CPU, ambient, chipset via `ipmitool`.
- **SMART** — SATA/SAS drive temps via `smartctl -j`.
- **NVMe** — NVMe temps via `nvme smart-log -o json`.
- **lm-sensors** — everything else the kernel exposes, via `sensors -j`.

Each sensor is classified into a **sensor class** (cpu, ambient, drive, nvme, other). Curves are per class. If a sensor reports a `temp_max` from the hardware, it overrides the curve's `temp_high` for that sensor.

### Fan control

On startup the daemon resets BMC fan sensor thresholds (to prevent the BMC from overriding manual duty cycles) and enables IPMI full manual fan mode. On exit it sets fans to full speed. Duty cycles are set via Supermicro-specific IPMI raw commands. The X11SCA-F has two fan zones: **cpu** and **peripheral**. A zone can have multiple fans — duty is set per zone, but each fan has its own RPM sensor. Stall detection and setpoint tracking are per fan. A zone's effective minimum duty is determined by whichever fan in the zone has the highest minimum setpoint.

### Control algorithm

Each sensor class has an interpolation curve: `temp_low`, `temp_high`, `duty_low`, `duty_high`. If a sensor reports a hardware `temp_max`, it overrides `temp_high` for that sensor. Between the two temps, duty is linearly interpolated. Below `temp_low` → `duty_low`. Above `temp_high` → `duty_high` (typically 100%). The resulting duty is then snapped to the nearest available setpoint for the fan.

Individual sensors can override any curve parameter via `[curves.sensor.<name>]` sections in the config. This is useful for components that run hotter than others in the same class (e.g. a NIC at 60°C idle vs DIMMs at 35°C, both classified as `other`). Unspecified fields inherit from the class curve.

Each curve feeds one or more fan zones. Per zone, the highest demand wins.

Default class-to-zone mapping:

| Sensor class | Fan zones |
|---|---|
| cpu | cpu, peripheral |
| ambient | peripheral |
| drive | peripheral |
| nvme | peripheral |
| other | peripheral |

### Calibration

`truefan init` steps through duty levels for each fan in 10% increments from 100% down, recording the RPM at each step. This builds a setpoint table (duty % → expected RPM) per fan. The lowest duty that kept the fan spinning becomes the minimum setpoint. `truefan recalibrate` re-runs this on an existing config (e.g. after cleaning or replacing fans). Calibration monitors IPMI temperatures throughout and aborts immediately if any sensor approaches its critical threshold.

During normal operation, if a fan stalls above its lowest setpoint, the daemon kicks the zone to 100%, removes that setpoint (raising the effective minimum), and saves the updated config.

### Configuration

Single TOML file via `tomlkit` — comments and formatting survive reads and writes. Has both user settings and daemon-managed state (setpoints, which you can also edit by hand). The daemon reloads the config on SIGHUP.

```toml
# Send SIGHUP to the daemon to reload this file.
poll_interval_seconds = 15
spindown_window_seconds = 180

# Curves map sensor temps to fan duty cycles, one per sensor class.
# Written by init for detected sensor classes. Example:
#
# [curves.<class>]
# temp_low = 35      # °C — below this, fans run at duty_low
# temp_high = 80     # °C — above this, fans run at duty_high
# duty_low = 25      # % — minimum demanded duty (snapped to nearest setpoint)
# duty_high = 100    # % — maximum demanded duty
# fan_zones = ["cpu", "peripheral"]

[curves.drive]
temp_low = 30
temp_high = 45
duty_low = 25
duty_high = 100
fan_zones = ["peripheral"]

# Per-sensor overrides — only the fields you want to change.
# Useful for components that run hotter than others in their class.
[curves.sensor.lmsensors-mlx5-pci-0200-sensor0]
temp_low = 60
temp_high = 95

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
    main.py          # entry point, argument parsing
    commands/
        __init__.py
        init.py      # detect fans, calibrate, generate config
        run.py       # start the daemon
        recalibrate.py # re-run fan calibration
        sensors.py   # show all detected sensors
        reload.py    # send SIGHUP to running daemon
    watchdog.py      # parent process — spawn, monitor, failsafe
    daemon.py        # main poll loop
    config.py        # load/save TOML, config dataclasses
    control.py       # interpolation math, max-demand-wins logic
    bmc.py           # BMC connection abstraction (BmcConnection ABC)
    fans.py          # fan duty commands, RPM reads, zone control
    sensors/
        __init__.py  # common SensorReading type, backend interface
        ipmi.py      # IPMI temp sensors
        smart.py     # SATA/SAS via smartctl -j
        nvme.py      # NVMe via nvme-cli
        lmsensors.py # lm-sensors via sensors -j
    calibrate.py     # ramp-down test + stall detection/recovery
    pidfile.py       # PID file locking for single-instance enforcement
    metrics.py       # statsd UDP push to Netdata
```

### Observability

The daemon pushes metrics to Netdata's statsd listener over UDP.

| Metric | Type | Meaning |
|---|---|---|
| `truefan.fan.<name>.target_rpm` | gauge | Expected RPM from the setpoint table at the current duty. Compare against actual RPM to spot anomalies. |
| `truefan.sensor.<name>.thermal_load` | gauge | How far each sensor is between its temp_low and temp_high (0-100%). |
| `truefan.sensor.<name>.temperature` | gauge | Current reading in °C. |
| `truefan.zone.<name>.duty` | gauge | Current duty cycle % for each fan zone. |
| `truefan.daemon.restarts` | counter | Incremented by the watchdog each time the daemon crashes and is restarted. |

The daemon also logs to stderr — fan speed changes, sensor errors, stall events.

To get proper chart names and units in Netdata, install `netdata/truefan.conf` into the Netdata container and restart it. This is only needed on the box running the daemon — streaming parents pick up the charts automatically.

### Failsafe

- **Crash:** watchdog sets all fans to 100%, restarts the daemon.
- **Sensor failure:** a single failed sensor is ignored (logged as a warning); the remaining sensors in its class still drive the curve. If *all* sensors in a class fail, the affected zones go to 100%.
- **Stall:** zone goes to 100%, recovery attempted, lowest setpoint removed and config saved.
- **Clean shutdown:** fans set to full speed.

## CLI

- **`truefan init [--config PATH]`** — detect sensors and fans, run calibration (build setpoint tables), write a config with curves for detected sensor classes and calibrated fan setpoints. Refuses if the config already exists.
- **`truefan run [--config PATH]`** — start the daemon (wrapped by the watchdog). Refuses if no config exists, pointing you to `truefan init`.
- **`truefan recalibrate [--config PATH]`** — re-run calibration on an existing config. Rebuilds setpoint tables in place and exits.
- **`truefan sensors`** — show all detected temperature and fan RPM sensors with current readings, classifications, and hardware thresholds. Useful for verifying what the daemon sees before running it.
- **`truefan reload`** — send SIGHUP to the running daemon to reload its config. Errors if no daemon is running.

Default config path: `truefan.toml` next to the script. `--config` overrides.
