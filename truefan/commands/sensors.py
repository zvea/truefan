"""The sensors subcommand: show all detected sensors."""

from truefan.bmc import IpmitoolConnection
from truefan.fans import FanControlError, fan_zone
from truefan.sensors import SensorReading, available_backends


def _fmt(value: float | None) -> str:
    """Format a float or None as a right-aligned string."""
    if value is None:
        return "-"
    return f"{value:.1f}"


def run_sensors() -> None:
    """Show all detected temperature and fan sensors with current readings."""
    bmc = IpmitoolConnection()
    backends = available_backends(bmc)

    readings: list[SensorReading] = []
    for backend in backends:
        readings.extend(backend.scan())
    readings.sort(key=lambda r: (r.sensor_class, r.name))

    # Temperature sensors table.
    name_width = max((len(r.name) for r in readings), default=10)
    print("Temperature sensors")
    print(f"  {'CLASS':<10} {'SENSOR':<{name_width}}  {'°C':>5}  {'MAX':>5}  {'CRIT':>5}")
    for r in readings:
        print(
            f"  {r.sensor_class:<10} {r.name:<{name_width}}"
            f"  {_fmt(r.temperature):>5}"
            f"  {_fmt(r.temp_max):>5}"
            f"  {_fmt(r.temp_crit):>5}"
        )

    # Fan sensors table.
    print()
    fan_list = bmc.list_fans()
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
