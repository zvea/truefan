# Changelog

## 0.9.1

- **Spindown window.** Fan speeds no longer drop the instant temps dip — the daemon holds the highest duty from the last 3 minutes (configurable via `spindown_window_seconds`).
- **BMC resilience.** Transient ipmitool failures are retried instead of crashing the daemon.
- **Thermal load metric.** Each sensor's position between its temp_low and temp_high is pushed to Netdata as a 0-100% gauge.
- **Temperature metric.** The daemon now pushes per-sensor °C readings to Netdata. Add the updated `truefan.conf` to your Netdata container to get the new chart.
- **Sensor names changed.** Hyphens are gone — everything is underscores now (`smart_sda`, `ipmi_CPU_Temp`, `lmsensors_coretemp_isa_0000_Core_0`). If you have `[curves.sensor.*]` overrides in your config, rename them to match.

## 0.9.0

- Initial release. Fan detection, calibration, IPMI/SMART/NVMe/lm-sensors backends, per-class curves, stall recovery, Netdata statsd integration.
