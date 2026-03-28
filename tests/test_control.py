"""Tests for truefan.control."""

from types import MappingProxyType

from truefan.config import Curve, FanConfig, SensorOverride
from truefan.control import compute_zone_duties, interpolate_duty, snap_duty_to_setpoint
from truefan.sensors import SensorClass, SensorReading



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _curve(
    temp_low: int = 30,
    temp_high: int = 50,
    duty_low: int = 20,
    duty_high: int = 100,
    fan_zones: frozenset[str] = frozenset({"peripheral"}),
) -> Curve:
    return Curve(
        temp_low=temp_low,
        temp_high=temp_high,
        duty_low=duty_low,
        duty_high=duty_high,
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

    def test_at_temp_low(self) -> None:
        """At temp_low, returns duty_low."""
        curve = _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 30.0) == 20.0

    def test_at_temp_high(self) -> None:
        """At temp_high, returns duty_high."""
        curve = _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 50.0) == 100.0

    def test_midpoint(self) -> None:
        """Midpoint temperature returns midpoint duty."""
        curve = _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 40.0) == 60.0

    def test_below_temp_low(self) -> None:
        """Below temp_low, clamps to duty_low."""
        curve = _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 10.0) == 20.0

    def test_above_temp_high(self) -> None:
        """Above temp_high, clamps to duty_high."""
        curve = _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 80.0) == 100.0

    def test_degenerate_equal_temps(self) -> None:
        """When temp_low == temp_high, returns duty_high."""
        curve = _curve(temp_low=40, temp_high=40, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 40.0) == 100.0

    def test_temp_high_override(self) -> None:
        """Hardware-reported temp_max overrides the curve's temp_high."""
        curve = _curve(temp_low=30, temp_high=80, duty_low=20, duty_high=100)
        # With override of 50, midpoint at 40 should give 60% (not 28%)
        assert interpolate_duty(curve, 40.0, temp_high_override=50.0) == 60.0

    def test_temp_high_override_none_uses_curve(self) -> None:
        """None override uses the curve's temp_high."""
        curve = _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100)
        assert interpolate_duty(curve, 40.0, temp_high_override=None) == 60.0


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
            SensorClass.DRIVE: _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [_reading(temperature=40.0, sensor_class=SensorClass.DRIVE)]

        result = compute_zone_duties(readings, curves, fans)
        # 40°C on 30-50 range, duty_low=20, duty_high=100 → duty=60, snap to 60
        assert result["peripheral"].duty == 60
        assert result["peripheral"].sensor_name == "sensor0"
        assert result["peripheral"].temperature == 40.0

    def test_max_temp_within_class(self) -> None:
        """Multiple sensors of same class — hottest one drives the zone."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [
            _reading(name="sda", temperature=35.0, sensor_class=SensorClass.DRIVE),
            _reading(name="sdb", temperature=45.0, sensor_class=SensorClass.DRIVE),
        ]

        result = compute_zone_duties(readings, curves, fans)
        # 45°C → duty=80, snaps to 80. sdb is the hottest.
        assert result["peripheral"].duty == 80
        assert result["peripheral"].sensor_name == "sdb"

    def test_multiple_classes_same_zone(self) -> None:
        """Different sensor classes feeding the same zone — highest demand wins."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(
                temp_low=30, temp_high=50, duty_low=20, duty_high=100,
                fan_zones=frozenset({"peripheral"}),
            ),
            SensorClass.AMBIENT: _curve(
                temp_low=25, temp_high=40, duty_low=20, duty_high=100,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [
            _reading(temperature=35.0, sensor_class=SensorClass.DRIVE),  # → duty 40
            _reading(temperature=38.0, sensor_class=SensorClass.AMBIENT),  # → duty ~89
        ]

        result = compute_zone_duties(readings, curves, fans)
        # Ambient demands ~89% — nearest setpoint is 80 (9.3 away vs 100 at 10.7)
        assert result["peripheral"].duty == 80

    def test_sensor_class_without_curve_ignored(self) -> None:
        """Sensors with no matching curve are ignored."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        readings = [
            _reading(temperature=40.0, sensor_class=SensorClass.DRIVE),
            _reading(temperature=99.0, sensor_class=SensorClass.NVME),  # no curve
        ]

        result = compute_zone_duties(readings, curves, fans)
        assert result["peripheral"].duty == 60

    def test_zone_with_no_sensors(self) -> None:
        """A fan zone with no sensors mapped to it is absent from the result."""
        curves = MappingProxyType({
            SensorClass.DRIVE: _curve(
                temp_low=30, temp_high=50, duty_low=20, duty_high=100,
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
            SensorClass.DRIVE: _curve(temp_low=30, temp_high=50, duty_low=20, duty_high=100),
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
        # Demanded duty = 40 (midpoint on 30-50, 20-100 range)
        # FAN1 snaps to 40, FAN2 snaps to 40 — zone gets 40
        assert result["peripheral"].duty == 40

    def test_sensor_temp_max_overrides_curve(self) -> None:
        """A sensor's hardware temp_max overrides the curve's temp_high."""
        curves = MappingProxyType({
            SensorClass.OTHER: _curve(
                temp_low=30, temp_high=80, duty_low=20, duty_high=100,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        # Mellanox NIC at 58°C with hardware temp_max=105
        # With curve temp_high=80: duty = 20 + (58-30)/(80-30) * 80 = 64.8 → snap 80
        # With temp_max=105:       duty = 20 + (58-30)/(105-30) * 80 = 49.9 → snap 60
        readings = [_reading(
            name="lmsensors/mlx5-pci-0200/sensor0",
            temperature=58.0,
            sensor_class=SensorClass.OTHER,
        )]
        result_without = compute_zone_duties(readings, curves, fans)

        readings_with_max = [SensorReading(
            name="lmsensors/mlx5-pci-0200/sensor0",
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
                temp_low=30, temp_high=80, duty_low=20, duty_high=100,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        # Two "other" sensors at the same temp.
        readings = [
            _reading(name="lmsensors/mlx5-pci-0200/sensor0", temperature=67.0,
                     sensor_class=SensorClass.OTHER),
            _reading(name="ipmi/PCH Temp", temperature=67.0,
                     sensor_class=SensorClass.OTHER),
        ]
        # Override only the NIC — raise temp_low so 67°C is barely above idle.
        overrides = MappingProxyType({
            "lmsensors/mlx5-pci-0200/sensor0": SensorOverride(temp_low=60, temp_high=95),
        })
        result_without = compute_zone_duties(readings, curves, fans)
        result_with = compute_zone_duties(readings, curves, fans, overrides)
        # With override, NIC demand is much lower; PCH still uses class curve.
        # PCH at 67°C on 30-80 curve: 20 + 37/50*80 = 79.2 → snap 80
        # NIC at 67°C on 60-95 curve: 20 + 7/35*80 = 36.0 → snap 40
        # Max is still PCH → same result as without override.
        assert result_with["peripheral"].duty == result_without["peripheral"].duty

    def test_sensor_override_reduces_demand_when_dominant(self) -> None:
        """Per-sensor override reduces demand when that sensor is the driver."""
        curves = MappingProxyType({
            SensorClass.OTHER: _curve(
                temp_low=30, temp_high=80, duty_low=20, duty_high=100,
                fan_zones=frozenset({"peripheral"}),
            ),
        })
        fans = MappingProxyType({"FAN1": _fan_config(zone="peripheral")})
        # Only the NIC — no other sensor to drive demand.
        readings = [
            _reading(name="lmsensors/mlx5-pci-0200/sensor0", temperature=67.0,
                     sensor_class=SensorClass.OTHER),
        ]
        overrides = MappingProxyType({
            "lmsensors/mlx5-pci-0200/sensor0": SensorOverride(temp_low=60, temp_high=95),
        })
        result_without = compute_zone_duties(readings, curves, fans)
        result_with = compute_zone_duties(readings, curves, fans, overrides)
        # Without override: 67°C on 30-80 → ~79% → snap 80
        # With override: 67°C on 60-95 → ~36% → snap 40
        assert result_with["peripheral"].duty < result_without["peripheral"].duty
        assert result_with["peripheral"].duty == 40
