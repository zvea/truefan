"""Shared mock implementations for tests."""

from truefan.bmc import BmcConnection, SelEntry, TemperatureSensorData


class FanSimulator(BmcConnection):
    """Simulates fans with configurable RPM-vs-duty and stall threshold.

    Each fan has a linear RPM curve and a stall duty below which it
    reports 0 RPM (or a spike if bmc_reset=True).
    """

    def __init__(
        self,
        fans: dict[str, dict],
        temps: list[TemperatureSensorData] | None = None,
        sel_entries: list[SelEntry] | None = None,
    ) -> None:
        """Fans is {name: {max_rpm, stall_below, bmc_reset}}.

        temps is an optional list of temperature sensor readings.
        sel_entries is an optional list of SEL entries to return.
        """
        self._fans = fans
        self._temps = temps or []
        self._sel_entries = sel_entries or []
        self._zone_duty: dict[str, int] = {}
        self._fan_zones: dict[str, str] = {}
        self.raw_commands: list[tuple[int, int, bytes]] = []

    def set_fan_zone(self, fan_name: str, zone: str) -> None:
        """Register which zone a fan belongs to."""
        self._fan_zones[fan_name] = zone

    def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
        """Record command, track zone duty for set_zone_duty calls."""
        self.raw_commands.append((netfn, command, data))
        if netfn == 0x30 and command == 0x70 and len(data) == 4 and data[0] == 0x66:
            zone_id = data[2]
            duty = data[3]
            zone_name = {0x00: "cpu", 0x01: "peripheral"}.get(zone_id, str(zone_id))
            self._zone_duty[zone_name] = duty
        return b""

    def set_sensor_thresholds(
        self, sensor_name: str,
        lower: tuple[int, int, int], upper: tuple[int, int, int],
    ) -> None:
        """No-op for tests."""

    def list_fans(self) -> list[tuple[str, int | None]]:
        """Return simulated fan RPMs based on current zone duties."""
        result: list[tuple[str, int | None]] = []
        for name, spec in self._fans.items():
            zone = self._fan_zones.get(name, "peripheral")
            duty = self._zone_duty.get(zone, 100)
            rpm = self._simulate_rpm(name, duty)
            result.append((name, rpm))
        return result

    def list_temperature_sensors(self) -> list[TemperatureSensorData]:
        """Return configured temperature sensor data."""
        return list(self._temps)

    def read_sel(self, last_n: int = 20) -> list[SelEntry]:
        """Return configured SEL entries."""
        return list(self._sel_entries[-last_n:])

    def _simulate_rpm(self, fan_name: str, duty: int) -> int | None:
        """Compute simulated RPM for a fan at a given duty."""
        spec = self._fans[fan_name]
        max_rpm = spec["max_rpm"]
        stall_below = spec.get("stall_below", 0)
        bmc_reset = spec.get("bmc_reset", False)
        if duty < stall_below:
            if bmc_reset:
                return max_rpm
            return 0
        return int(max_rpm * duty / 100)


def noop_sleep(seconds: float) -> None:
    """No-op sleep for tests."""
