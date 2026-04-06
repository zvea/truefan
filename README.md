# truefan

Fan control daemon for TrueNAS SCALE systems on Supermicro X11 boards. Takes
over fan control from the BMC so you can tune noise vs. cooling to your
environment. Reads temperatures from IPMI, SMART, NVMe, and lm-sensors, then
sets fan duty cycles via IPMI raw commands. Metrics go to Netdata via statsd.

## Features

- **Auto-detection** of sensors and fans — classifies by type (cpu, drive,
  nvme, ambient, other) and applies per-class interpolation curves.
- **Self-calibrating** — learns each fan's setpoint table by ramping duty
  down and recording RPMs. Can be recalibrated as fans age or collect dust.
- **Failsafe** — fans go to 100% on crash, total sensor class failure, or
  stalled fan. The watchdog parent restarts the daemon automatically.
- **Config validation** — startup, reload, and the `check` command validate
  config syntax, values, and hardware match before touching any fans.
- **Syslog logging** — the daemon logs to syslog; `truefan logs` wraps
  journalctl for easy access.
- **Netdata metrics** — per-sensor temperature and thermal load, per-zone
  duty, per-fan target RPM, daemon uptime, and restart count via statsd.
  Optional alert configs included.

## Requirements

- Python 3.11+
- `ipmitool`
- `smartctl` (smartmontools) — for SATA/SAS drive temps
- `nvme-cli` — for NVMe temps
- `lm-sensors` — for kernel-exposed sensors
- Supermicro X11 motherboard with IPMI

## Install

TrueNAS SCALE doesn't ship `ensurepip`, so create the venv without it and
bootstrap pip manually:

```bash
python3 -m venv --without-pip /mnt/pool1/venvs/truefan
source /mnt/pool1/venvs/truefan/bin/activate
curl -sS https://bootstrap.pypa.io/get-pip.py | python3
pip install truefan
```

Put the venv on a pool — the boot drive is wiped on OS updates.

## Quick start

```bash
# Detect sensors, calibrate fans, write config
# (ramps fans up and down for a few minutes)
sudo truefan init

# Start the daemon (daemonizes and returns immediately)
sudo truefan start

# Check if it's running
truefan status

# Show detected sensors and current readings
truefan sensors

# Follow daemon logs
truefan logs -f

# Reload config without restarting
sudo truefan reload

# Re-calibrate after cleaning or replacing fans
sudo truefan recalibrate

# Stop the daemon
sudo truefan stop
```

To get Netdata dashboards and alerts, install the bundled configs:

```bash
truefan netdata install
```

Use `truefan netdata uninstall` to remove them. Use `truefan netdata check` to verify
configs are up to date.

## Configuration

`truefan init` generates a `truefan.toml` with sensible defaults. Example:

```toml
poll_interval_seconds = 15
spindown_window_seconds = 180

[thermal.class.drive]
no_cooling_temp = 30
max_cooling_temp = 45
fan_zones = ["peripheral"]

# Per-sensor overrides for components that run hotter than their class
[thermal.sensor.lmsensors_mlx5_pci_0200_sensor0]
no_cooling_temp = 60
max_cooling_temp = 95

# Learned via calibration — duty % = expected RPM
[fans.FAN1]
zone = "cpu"

[fans.FAN1.setpoints]
25 = 320
30 = 450
40 = 620
50 = 780
100 = 1500
```

Use `--config PATH` with any command to specify an alternate config location.

## Running on boot

TrueNAS SCALE's **Init/Shutdown Scripts** (under **System > Advanced**) run
commands at boot and shutdown.

Add a script (Type: Command, When: Post Init):

```
/mnt/pool1/venvs/truefan/bin/truefan start
```

No tmux or nohup needed — `start` forks into the background on its own.
Use `truefan logs -f` to follow output and `truefan status` to check if
it's running.

## How it works

Each sensor class has a temperature-to-duty curve. Between `no_cooling_temp`
and `max_cooling_temp`, duty is linearly interpolated from 0% to 100%;
hardware-reported thermal limits override `max_cooling_temp` when available.
The hottest sensor in each fan zone sets the duty, which is then snapped to
the nearest calibrated fan setpoint. A spindown window prevents rapid cycling.

If a fan stalls, the zone goes to 100% and the lowest setpoint is removed
so the minimum duty rises going forward.

Send SIGUSR1 to dump current sensor readings, thermal loads, and zone
duties to syslog (`kill -USR1 $(cat /var/run/truefan.pid)`; view with
`truefan logs`).

## License

MIT
