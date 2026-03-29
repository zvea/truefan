# Changelog

## 1.2.2

- **SIGUSR1 no longer kills the watchdog.** Previously, sending SIGUSR1 to dump state would kill the watchdog (unhandled signal), leaving the daemon child running unsupervised with a stale PID file. The watchdog now forwards SIGUSR1 to the child correctly.
- **Clean shutdown on watchdog death.** If the watchdog dies unexpectedly, the daemon child now receives SIGTERM automatically and shuts down with fans at full speed. Previously the child would keep running without a safety net.
- **PID file lock no longer leaks to child.** The daemon child no longer inherits the PID file lock. Previously, killing the watchdog left the lock held by the child, making `truefan stop` and `truefan start` unable to recover without manually finding and killing the child process.

## 1.2.1

- **State dump via SIGUSR1.** Send `kill -USR1` to the daemon to log current sensor readings, thermal loads, and zone duties to syslog. Useful for debugging why fans are at a given speed without restarting.
- **Ghost sensor fix.** IPMI sensors with empty names are now skipped. Previously they appeared as `ipmi_` in Netdata dashboards.

## 1.2.0

- **Config format changed.** `[curves.<class>]` sections are now `[thermal.class.<class>]` and `[curves.sensor.<name>]` overrides are now `[thermal.sensor.<name>]`. The fields `temp_low`/`temp_high` are renamed to `no_cooling_temp`/`max_cooling_temp`. The `duty_low` and `duty_high` fields are removed. You must update your `truefan.toml` to match, or delete it and re-run `truefan init` — the daemon will refuse to start with the old format.
- **Simpler duty cycle model.** Duty cycle is now interpolated from 0% to 100% across the temperature range. Fan calibration setpoints handle the physical minimum — no need to configure duty cycle bounds per sensor class.
- **Init shows sensor counts.** `truefan init` now shows how many sensors were detected in each class.

## 1.1.0

- **Netdata setup overhaul.** `install.sh` is now `setup.sh` with `install`/`uninstall` commands replacing the old `child`/`parent`/`standalone` roles. Config files moved to `netdata/statsd.d/` and `netdata/health.d/` to mirror the Netdata directory layout.
- **Not-reporting alert fix.** The `truefan_not_reporting` alert now detects a stale uptime counter instead of checking for NaN, which Netdata's statsd synthetic charts never produce — they repeat the last gauge value forever.

## 1.0.0

- **Daemon lifecycle.** New `start`, `stop`, `restart` commands replace the old `run` command. The daemon now double-forks, writes a PID file, and returns your shell immediately. `truefan status` checks if it's running.
- **Config validation.** `truefan check` validates the config file (use `--syntax-only` to skip hardware checks). `truefan start` and `truefan reload` now validate config values — types, ranges, zone consistency — and verify fans and sensor overrides against live hardware before doing anything.
- **Syslog logging.** The daemon logs to syslog (`LOG_DAEMON` facility) instead of stderr. `truefan logs` shows daemon logs via journalctl, forwarding any extra arguments (e.g. `truefan logs -f`).
- **Netdata alerts.** Alert definitions ship in `netdata/health.d/` alongside the statsd app config in `netdata/statsd.d/`. The install script (`setup.sh install`/`uninstall`) copies both into the container. It warns when installing into ephemeral container storage.
- **Uptime metric.** `truefan.daemon.uptime` gauge tracks seconds since the daemon started its main loop.
- **CLI polish.** `--version` flag, `--config` accepted before or after the subcommand, better error messages for missing IPMI device and permission issues.

## 0.9.1

- **Spindown window.** Fan speeds no longer drop the instant temps dip — the daemon holds the highest duty from the last 3 minutes (configurable via `spindown_window_seconds`).
- **BMC resilience.** Transient ipmitool failures are retried instead of crashing the daemon.
- **Thermal load metric.** Each sensor's position between its temp_low and temp_high is pushed to Netdata as a 0-100% gauge.
- **Temperature metric.** The daemon now pushes per-sensor °C readings to Netdata. Add the updated `truefan.conf` to your Netdata container to get the new chart.
- **Sensor names changed.** Hyphens are gone — everything is underscores now (`smart_sda`, `ipmi_CPU_Temp`, `lmsensors_coretemp_isa_0000_Core_0`). If you have `[curves.sensor.*]` overrides in your config, rename them to match.

## 0.9.0

- Initial release. Fan detection, calibration, IPMI/SMART/NVMe/lm-sensors backends, per-class curves, stall recovery, Netdata statsd integration.
