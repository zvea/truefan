"""Tests for truefan.control."""

from types import MappingProxyType

from truefan.config import Curve, FanConfig, SensorOverride
from truefan.control import (
    compute_thermal_load,
    compute_zone_duties,
    interpolate_duty,
    snap_duty_to_setpoint,
)
from truefan.sensors import SensorClass, SensorReading



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _curve(
    no_cooling_temp: int = 30,
    max_cooling_temp: int = 50,
    fan_zones: frozenset[str] = frozenset({"peripheral"}),
) -> Curve:
    return Curve(
        no_cooling_temp=no_cooling_temp,
        max_cooling_temp=max_cooling_temp,
        fan_zones=fan_zones,
    )


def _reading(
    name: str = "sensor0",
    sensor_class: SensorClass = SensorClass.DRIVE,
    temperature: float = 40.0,
) -> SensorReading:
    return SensorReading(name=name, sensor_class=sensor_class, temperature=temperature)


def _fan_config(
    zone: str = "peripheral",
    setpoints: dict[int, int] | None = None,
) -> FanConfig:
    if setpoints is None:
        setpoints = {20: 300, 40: 600, 60: 900, 80: 1200, 100: 1500}
    return FanConfig(zone=zone, setpoints=MappingProxyType(setpoints))


# ---------------------------------------------------------------------------
# #### interpolate_duty
# ---------------------------------------------------------------------------

class TestInterpolateDuty:
    """Tests for interpolate_duty."""

    def test_at_no_cooling_temp(self) -> None:
        """At no_cooling_temp, returns 0%."""
        assert interpolate_duty(_curve(), 30.0) == 0.0

    def test_at_max_cooling_temp(self) -> None:
        """At max_cooling_temp, returns 100%."""
        assert interpolate_duty(_curve(), 50.0) == 100.0

    def test_midpoint(self) -> None:
        """Midpoint temperature returns 50%."""
        assert interpolate_duty(_curve(), 40.0) == 50.0

    def test_below_no_cooling_temp(self) -> None:
        """Below no_cooling_temp, clamps to 0%."""
        assert interpolate_duty(_curve(), 10.0) == 0.0

    def test_above_max_cooling_temp(self) -> None:
        """Above max_cooling_temp, clamps to 100%."""
        assert interpolate_duty(_curve(), 80.0) == 100.0

    def test_degenerate_equal_temps(self) -> None:
        """When no_cooling_temp == max_cooling_temp, returns 100%."""
        curve = _curve(no_cooling_temp=40, max_cooling_temp=40)
        assert interpolate_duty(curve, 40.0) == 100.0

    def test_max_cooling_temp_override(self) -> None:
        """Hardware-reported temp_max overrides the curve's max_cooling_temp."""
        curve = _curve(no_cooling_temp=30, max_cooling_temp=80)
        # With override of 50, midpoint at 40 should give 50%
        assert interpolate_duty(curve, 40.0, max_cooling_temp_override=50.0) == 50.0

    def test_max_cooling_temp_override_none_uses_curve(self) -> None:
        """None override uses the curve's max_cooling_temp."""
        assert interpolate_duty(_curve(), 40.0, max_cooling_temp_override=None) == 50.0


# ---------------------------------------------------------------------------
# #### compute_thermal_load
# ---------------------------------------------------------------------------

class TestComputeThermalLoad:
    """Tests for compute_thermal_load."""

    def test_midpoint(self) -> None:
        """Midpoint temperature returns 50% load."""
        reading = SensorReading(
            name="s", sensor_class=SensorClass.DRIVE, temperature=40.0,
        )
        assert compute_thermal_load(reading, _curve()) == 50.0

    def test_below_no_cooling_temp(self) -> None:
        """Below no_cooling_temp clamps to 0%."""
        reading = SensorReading(
            name="s", sensor_class=SensorClass.DRIVE, temperature=20.0,
        )
        assert compute_thermal_load(reading, _curve()) == 0.0

    def test_above_max_cooling_temp(self) -> None:
        """Above max_cooling_temp clamps to 100%."""
        reading = SensorReading(
            name="s", sensor_class=SensorClass.DRIVE, temperature=60.0,
        )
        assert compute_thermal_load(reading, _curve()) == 100.0

    def test_degenerate_equal_temps(self) -> None:
        """When no_cooling_temp == max_cooling_temp, returns 100%."""
        curve = _curve(no_cooling_temp=40, max_cooling_temp=40)
        reading = SensorReading(
            name="s", sensor_class=SensorClass.DRIVE, temperature=40.0,
        )
        assert compute_thermal_load(reading, curve) == 100.0

    def test_override_changes_range(self) -> None:
        """Per-sensor override adjusts the effective temperature range."""
        curve = _curve(no_cooling_temp=30, max_cooling_temp=80)
        override = SensorOverride(no_cooling_temp=60, max_cooling_temp=95)
        reading = SensorReading(
            name="s", sensor_class=SensorClass.OTHER, temperature=67.0,
        )
        load_without = compute_thermal_load(reading, curve)
        load_with = compute_thermal_load(reading, curve, override)
        # 67°C on 30-80 → 74%, on 60-95 → 20%
        assert load_with < load_without

    def test_hardware_temp_max_overrides_curve(self) -> None:
        """Hardware temp_max replaces max_cooling_temp when no override sets it."""
        curve = _curve(no_cooling_temp=30, max_cooling_temp=80)
        reading = SensorReading(
            name="s", sensor_class=SensorClass.OTHER,
            temperature=55.0, temp_max=105.0,
        )
        load = compute_thermal_load(reading, curve)
        # 55°C on 30-105 → 33.3%
        assert round(load, 1) == 33.3

    def test_override_max_cooling_temp_beats_hardware_temp_max(self) -> None:
        """When override sets max_cooling_temp, hardware temp_max is ignored."""
        curve = _curve(no_cooling_temp=30, max_cooling_temp=80)
        override = SensorOverride(max_cooling_temp=60)
        reading = SensorReading(
            name="s", sensor_class=SensorClass.OTHER,
            temperature=45.0, temp_max=105.0,
        )
        load = compute_thermal_load(reading, curve, override)
        # 45°C on 30-60 → 50% (temp_max=105 ignored because override sets max_cooling_temp)
        assert load == 50.0


# ---------------------------------------------------------------------------
# #### snap_duty_to_setpoint
# ---------------------------------------------------------------------------

class TestSnapDutyToSetpoint:
    """Tests for snap_duty_to_setpoint."""

    def test_exact_match(self) -> None:
        """Exact match on a setpoint returns that setpoint's duty."""
        setpoints = MappingProxyType({20: 300, 40: 600, 60: 900, 100: 1500})
        assert snap_duty_to_setpoint(40.0, setpoints) == 40

    def test_between_setpoints_snaps_nearest_up(self) -> None:
        """Between two setpoints, closer to the higher — snaps up."""
        setpoints = MappingProxyType({20: 300, 40: 600, 60: 900, 100: 1500})
        assert snap_duty_to_setpoint(35.0, setpoints) == 40

    def test_between_setpoints_snaps_nearest_down(self) -> None:
        """Between two setpoints, closer to the lower — snaps down."""
        setpoints = MappingProxyType({20: 300, 40: 600, 60: 900, 100: 1500})
        assert snap_duty_to_setpoint(25.0, setpoints) == 20

    def test_below_lowest(self) -> None:
        """Below the lowest setpoint, returns the lowest."""
        setpoints = MappingProxyType({20: 300, 40: 600, 60: 900, 100: 1500})
        assert snap_duty_to_setpoint(10.0, setpoints) == 20

    def test_above_highest(self) -> None:
        """Above the highest setpoint, returns the highest."""
        setpoints = MappingProxyType({20: 300, 40: 600, 60: 900, 100: 1500})
        assert snap_duty_to_setpoint(110.0, setpoints) == 100

    def test_single_setpoint(self) -> None:
        """Single setpoint is always returned."""
        setpoints = MappingProxyType({50: 800})
        assert snap_duty_to_setpoint(30.0, setpoints) == 50


# ---------------------------------------------------------------------------
# #### compute_zone_duties
# ---------------------------------------------------------------------------

class TestComputeZoneDuties:
    """Tests for compute_zone_duties."""

    def test_single_sensor_single_zone(self) -> None:
        """One sensor, one zone, one fan — straightforward demand."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(no_cooling_temp=30, max_cooling_temp=50),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [_reading(temperature=40.0, sensor_class=SensorClass.DRIVE)]

        result = compute_zone_duties(readings, curves, fans)
        # 40°C on 30-50 range → 50% duty, snap to 40
        assert result["peripheral"].duty == 40
        assert result["peripheral"].sensor_name == "sensor0"
        assert result["peripheral"].temperature == 40.0

    def test_max_temp_within_class(self) -> None:
        """Multiple sensors of same class — hottest one drives the zone."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(no_cooling_temp=30, max_cooling_temp=50),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [
            _reading(name="sda", temperature=35.0, sensor_class=SensorClass.DRIVE),
            _reading(name="sdb", temperature=45.0, sensor_class=SensorClass.DRIVE),
        ]

        result = compute_zone_duties(readings, curves, fans)
        # sdb at 45°C → 75%, snaps to 80. sdb is the hottest.
        assert result["peripheral"].duty == 80
        assert result["peripheral"].sensor_name == "sdb"

    def test_multiple_classes_same_zone(self) -> None:
        """Different sensor classes feeding the same zone — highest demand wins."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(
                no_cooling_temp=30, max_cooling_temp=50,
                fan_zones=frozenset({"peripheral"}),
            ),
            SensorClass.AMBIENT: _curve(
                no_cooling_temp=25, max_cooling_temp=40,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [
            _reading(temperature=35.0, sensor_class=SensorClass.DRIVE),  # → 25%
            _reading(temperature=38.0, sensor_class=SensorClass.AMBIENT),  # → ~86.7%
        ]

        result = compute_zone_duties(readings, curves, fans)
        # Ambient demands ~86.7% — nearest setpoint is 80
        assert result["peripheral"].duty == 80

    def test_sensor_class_without_curve_ignored(self) -> None:
        """Sensors with no matching curve are ignored."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(no_cooling_temp=30, max_cooling_temp=50),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [
            _reading(temperature=40.0, sensor_class=SensorClass.DRIVE),
            _reading(temperature=99.0, sensor_class=SensorClass.NVME),  # no curve
        ]

        result = compute_zone_duties(readings, curves, fans)
        # Drive at 40°C → 50%, snap to 40 (nearest to 50 is 40 or 60, equidistant → 40 wins)
        assert result["peripheral"].duty == 40

    def test_zone_with_no_sensors(self) -> None:
        """A fan zone with no sensors mapped to it is absent from the result."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(
                no_cooling_temp=30, max_cooling_temp=50,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({
            "FAN1": _fan_config(zone="peripheral"),
            "FAN2": _fan_config(zone="cpu"),
        })
        readings = [_reading(temperature=40.0, sensor_class=SensorClass.DRIVE)]

        result = compute_zone_duties(readings, curves, fans)
        assert "peripheral" in result
        assert "cpu" not in result

    def test_two_fans_same_zone_different_setpoints(self) -> None:
        """Two fans in the same zone with different setpoints — zone duty satisfies both."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(no_cooling_temp=30, max_cooling_temp=50),
        })
        fans = MappingProxyType({
            "FAN1": _fan_config(
                zone="peripheral",
                setpoints={20: 300, 40: 600, 60: 900, 100: 1500},
            ),
            "FAN2": _fan_config(
                zone="peripheral",
                # Lost its lowest setpoint — minimum is now 40
                setpoints={40: 550, 60: 850, 100: 1400},
            ),
        })
        readings = [_reading(temperature=35.0, sensor_class=SensorClass.DRIVE)]

        result = compute_zone_duties(readings, curves, fans)
        # Demanded duty = 25% (midpoint on 30-50 → 25%)
        # FAN1 snaps to 20, FAN2 snaps to 40 — zone gets max = 40
        assert result["peripheral"].duty == 40

    def test_sensor_temp_max_overrides_curve(self) -> None:
        """A sensor's hardware temp_max overrides the curve's max_cooling_temp."""
        curves = MappingProxyType({
            SensorClass.OTHER: _curve(
                no_cooling_temp=30, max_cooling_temp=80,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        # Mellanox NIC at 58°C with hardware temp_max=105
        # With curve max_cooling_temp=80: duty = (58-30)/(80-30) * 100 = 56% → snap 60
        # With temp_max=105:              duty = (58-30)/(105-30) * 100 = 37.3% → snap 40
        readings = [_reading(
            name="lmsensors_mlx5_pci_0200_sensor0",
            temperature=58.0,
            sensor_class=SensorClass.OTHER,
        )]
        result_without = compute_zone_duties(readings, curves, fans)

        readings_with_max = [SensorReading(
            name="lmsensors_mlx5_pci_0200_sensor0",
            sensor_class=SensorClass.OTHER,
            temperature=58.0,
            temp_max=105.0,
        )]
        result_with = compute_zone_duties(readings_with_max, curves, fans)
        # With hardware temp_max, demand is lower → lower setpoint
        assert result_with["peripheral"].duty < result_without["peripheral"].duty

    def test_sensor_override_changes_curve(self) -> None:
        """A per-sensor override adjusts the curve for that sensor only."""
        curves = MappingProxyType({
            SensorClass.OTHER: _curve(
                no_cooling_temp=30, max_cooling_temp=80,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        # Two "other" sensors at the same temp.
        readings = [
            _reading(name="lmsensors_mlx5_pci_0200_sensor0", temperature=67.0,
                     sensor_class=SensorClass.OTHER),
            _reading(name="ipmi_PCH_Temp", temperature=67.0,
                     sensor_class=SensorClass.OTHER),
        ]
        # Override only the NIC — raise no_cooling_temp so 67°C is barely above idle.
        overrides = MappingProxyType({
            "lmsensors_mlx5_pci_0200_sensor0": SensorOverride(no_cooling_temp=60, max_cooling_temp=95),
        })
        result_without = compute_zone_duties(readings, curves, fans)
        result_with = compute_zone_duties(readings, curves, fans, overrides)
        # With override, NIC demand is much lower; PCH still uses class curve.
        # PCH at 67°C on 30-80 curve: (67-30)/(80-30)*100 = 74% → snap 80
        # NIC at 67°C on 60-95 curve: (67-60)/(95-60)*100 = 20% → snap 20
        # Max is still PCH → same result as without override.
        assert result_with["peripheral"].duty == result_without["peripheral"].duty

    def test_sensor_override_reduces_demand_when_dominant(self) -> None:
        """Per-sensor override reduces demand when that sensor is the driver."""
        curves = MappingProxyType({
            SensorClass.OTHER: _curve(
                no_cooling_temp=30, max_cooling_temp=80,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        # Only the NIC — no other sensor to drive demand.
        readings = [
            _reading(name="lmsensors_mlx5_pci_0200_sensor0", temperature=67.0,
                     sensor_class=SensorClass.OTHER),
        ]
        overrides = MappingProxyType({
            "lmsensors_mlx5_pci_0200_sensor0": SensorOverride(no_cooling_temp=60, max_cooling_temp=95),
        })
        result_without = compute_zone_duties(readings, curves, fans)
        result_with = compute_zone_duties(readings, curves, fans, overrides)
        # Without override: 67°C on 30-80 → 74% → snap 80
        # With override: 67°C on 60-95 → 20% → snap 20
        assert result_with["peripheral"].duty < result_without["peripheral"].duty
        assert result_with["peripheral"].duty == 20
