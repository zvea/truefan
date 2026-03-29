# Changelog

## 1.0.0

- **Daemon lifecycle.** New `start`, `stop`, `restart` commands replace the old `run` command. The daemon now double-forks, writes a PID file, and returns your shell immediately. `truefan status` checks if it's running.
- **Config validation.** `truefan check` validates the config file (use `--syntax-only` to skip hardware checks). `truefan start` and `truefan reload` now validate config values — types, ranges, zone consistency — and verify fans and sensor overrides against live hardware before doing anything.
- **Syslog logging.** The daemon logs to syslog (`LOG_DAEMON` facility) instead of stderr. `truefan logs` shows daemon logs via journalctl, forwarding any extra arguments (e.g. `truefan logs -f`).
- **Netdata alerts.** Alert definitions ship in `netdata/parent/` alongside the existing statsd app config in `netdata/child/`. The install script supports `child`, `parent`, and `standalone` roles. It warns when installing into ephemeral container storage.
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
