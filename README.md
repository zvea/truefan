# truefan

Fan control daemon for TrueNAS SCALE systems on Supermicro X11 boards. Reads
temperatures from IPMI, SMART, NVMe, and lm-sensors, then adjusts fan duty
cycles via IPMI raw commands to keep things cool with minimal noise.

## Features

- **Auto-detection** of sensors and fans — classifies by type (cpu, drive,
  nvme, ambient, other) and applies per-class interpolation curves.
- **Self-calibrating** — learns each fan's setpoint table by ramping duty
  down and recording RPMs. Can be recalibrated as fans age or collect dust.
- **Failsafe** — fans go to 100% on crash, total sensor class failure, or
  stalled fan. The watchdog parent restarts the daemon automatically.
- **Netdata metrics** — per-sensor thermal load, per-zone duty, per-fan
  target RPM, and daemon restart count via statsd.

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
sudo truefan init

# Start the daemon
sudo truefan run

# Show detected sensors and current readings
truefan sensors

# Re-calibrate after cleaning or replacing fans
sudo truefan recalibrate

# Reload config without restarting
sudo truefan reload
```

## Configuration

`truefan init` generates a `truefan.toml` with sensible defaults. Example:

```toml
poll_interval_seconds = 15
spindown_window_seconds = 180

[curves.drive]
temp_low = 30
temp_high = 45
duty_low = 25
duty_high = 100
fan_zones = ["peripheral"]

# Per-sensor overrides for components that run hotter than their class
[curves.sensor.lmsensors-mlx5-pci-0200-sensor0]
temp_low = 60
temp_high = 95

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
commands at boot and shutdown. Use `tmux` to run the daemon in a detachable
session you can attach to later for debugging.

Add a script (Type: Command, When: Post Init):

```
tmux new-session -d -s truefan '/mnt/pool1/venvs/truefan/bin/truefan run 2>&1 | tee /var/log/truefan.log'
```

To check on the daemon: `tmux attach -t truefan`. Detach with `Ctrl-b d`.

## How it works

Each sensor class has a temperature-to-duty curve. Between `temp_low` and
`temp_high`, duty is linearly interpolated; hardware-reported thermal limits
override `temp_high` when available. The hottest sensor in each fan zone
sets the duty. A spindown window prevents rapid cycling.

If a fan stalls, the zone goes to 100% and the lowest setpoint is removed
so the minimum duty rises going forward.

## License

MIT
