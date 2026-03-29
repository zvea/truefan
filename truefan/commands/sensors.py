"""The sensors subcommand: show all detected sensors."""

import logging

from truefan.bmc import BmcConnection, IpmitoolConnection, ipmi_device_present
from truefan.fans import FanControlError, fan_zone
from truefan.sensors import SensorReading, available_backends

_log: logging.Logger = logging.getLogger(__name__)


def _fmt(value: float | None) -> str:
    """Format a float or None as a right-aligned string."""
    if value is None:
        return "-"
    return f"{value:.1f}"


def _try_connect_bmc() -> BmcConnection | None:
    """Create a BMC connection if an IPMI device is present."""
    if not ipmi_device_present():
        return None
    return IpmitoolConnection()


def run_sensors(conn: BmcConnection | None = None) -> None:
    """Show all detected temperature and fan sensors with current readings.

    Works without IPMI — shows whatever sensor backends are available
    and skips fans if BMC is unreachable.
    """
    if conn is None:
        conn = _try_connect_bmc()

    backends = available_backends(conn)

    readings: list[SensorReading] = []
    for backend in backends:
        try:
            readings.extend(backend.scan())
        except Exception:
            _log.debug("Backend %s failed", type(backend).__name__, exc_info=True)
    readings.sort(key=lambda r: (r.sensor_class, r.name))

    # Temperature sensors table.
    if readings:
        name_width = max(len(r.name) for r in readings)
        print("Temperature sensors")
        print(f"  {'CLASS':<10} {'SENSOR':<{name_width}}  {'°C':>5}  {'MAX':>5}  {'CRIT':>5}")
        for r in readings:
            print(
                f"  {r.sensor_class:<10} {r.name:<{name_width}}"
                f"  {_fmt(r.temperature):>5}"
                f"  {_fmt(r.temp_max):>5}"
                f"  {_fmt(r.temp_crit):>5}"
            )
    else:
        print("No temperature sensors detected.")

    # Fan sensors table.
    if conn is not None:
        print()
        fan_list = conn.list_fans()
        if fan_list:
            fan_name_width = max(len(name) for name, _ in fan_list)
            print("Fan sensors")
            print(f"  {'FAN':<{fan_name_width}}  {'ZONE':<12}  {'RPM':>5}")
            for name, rpm in fan_list:
                try:
                    zone = fan_zone(name)
                except FanControlError:
                    zone = "?"
                rpm_str = str(rpm) if rpm is not None else "-"
                print(f"  {name:<{fan_name_width}}  {zone:<12}  {rpm_str:>5}")
    else:
        print("\nNo IPMI device found — fan sensors not available.")
