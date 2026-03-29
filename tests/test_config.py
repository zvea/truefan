"""Tests for truefan.config."""

from pathlib import Path
from types import MappingProxyType

import pytest

from tests.mocks import FanSimulator
from truefan.config import (
    DEFAULT_CURVES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    Config,
    ConfigError,
    Curve,
    FanConfig,
    load_config,
    save_config,
    validate_config,
)
from truefan.sensors import SensorClass, SensorReading


# ---------------------------------------------------------------------------
# #### load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    """Tests for load_config."""

    def test_minimal_config(self, tmp_path: Path) -> None:
        """Config with just poll_interval and fans has no curves."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        config = load_config(cfg)
        assert config.poll_interval_seconds == 5
        assert len(config.curves) == 0
        assert "FAN1" in config.fans
        assert config.fans["FAN1"].zone == "cpu"
        assert dict(config.fans["FAN1"].setpoints) == {25: 320, 100: 1500}

    def test_curve_override(self, tmp_path: Path) -> None:
        """A thermal class section replaces the default for that class."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[thermal.class.drive]\n'
            'no_cooling_temp = 25\n'
            'max_cooling_temp = 40\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '30 = 400\n'
            '100 = 1500\n'
        )
        config = load_config(cfg)
        drive_curve = config.curves[SensorClass.DRIVE]
        assert drive_curve.no_cooling_temp == 25
        assert drive_curve.max_cooling_temp == 40
        assert drive_curve.fan_zones == frozenset({"peripheral"})

    def test_partial_curve_overrides(self, tmp_path: Path) -> None:
        """Only explicitly listed sensor classes have curves."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[thermal.class.cpu]\n'
            'no_cooling_temp = 40\n'
            'max_cooling_temp = 90\n'
            'fan_zones = ["cpu"]\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '30 = 400\n'
            '100 = 1500\n'
        )
        config = load_config(cfg)
        assert config.curves[SensorClass.CPU].no_cooling_temp == 40
        assert len(config.curves) == 1

    def test_missing_poll_interval_uses_default(self, tmp_path: Path) -> None:
        """Missing poll_interval_seconds falls back to the default."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        config = load_config(cfg)
        assert config.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS

    def test_missing_file(self, tmp_path: Path) -> None:
        """Missing config file raises ConfigError."""
        with pytest.raises(ConfigError):
            load_config(tmp_path / "nonexistent.toml")

    def test_malformed_toml(self, tmp_path: Path) -> None:
        """Malformed TOML raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("[invalid\n")
        with pytest.raises(ConfigError):
            load_config(cfg)

    def test_no_cooling_temp_exceeds_max_cooling_temp(self, tmp_path: Path) -> None:
        """Curve with no_cooling_temp > max_cooling_temp raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[thermal.class.drive]\n'
            'no_cooling_temp = 50\n'
            'max_cooling_temp = 30\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        with pytest.raises(ConfigError):
            load_config(cfg)

    def test_sensor_overrides(self, tmp_path: Path) -> None:
        """Per-sensor overrides are parsed from [thermal.sensor.*] sections."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[thermal.class.other]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[thermal.sensor.lmsensors_mlx5_pci_0200_sensor0]\n'
            'no_cooling_temp = 60\n'
            'max_cooling_temp = 95\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        config = load_config(cfg)
        assert "lmsensors_mlx5_pci_0200_sensor0" in config.sensor_overrides
        override = config.sensor_overrides["lmsensors_mlx5_pci_0200_sensor0"]
        assert override.no_cooling_temp == 60
        assert override.max_cooling_temp == 95
        assert override.fan_zones is None

    def test_unknown_sensor_class(self, tmp_path: Path) -> None:
        """Curve for an unknown sensor class raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[thermal.class.unknown]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 50\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        with pytest.raises(ConfigError):
            load_config(cfg)

    def test_unrecognized_top_level_section(self, tmp_path: Path) -> None:
        """Unrecognized top-level section raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[fnas.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fnas.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        with pytest.raises(ConfigError, match="fnas"):
            load_config(cfg)

    def test_multiple_unrecognized_sections(self, tmp_path: Path) -> None:
        """All unrecognized sections are named in the error."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[blah]\n'
            'x = 1\n'
            '\n'
            '[stuff]\n'
            'y = 2\n'
        )
        with pytest.raises(ConfigError, match="blah"):
            load_config(cfg)

    def test_fan_missing_zone(self, tmp_path: Path) -> None:
        """Fan section without zone raises ConfigError naming the fan and key."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[fans.FAN1]\n'
            'x = 1\n'
        )
        with pytest.raises(ConfigError, match=r"\[fans\.FAN1\].*missing.*zone"):
            load_config(cfg)

    def test_fan_setpoints_only_suggests_typo(self, tmp_path: Path) -> None:
        """Fan with only setpoints suggests the section header is misspelled."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        with pytest.raises(ConfigError, match=r"misspelled"):
            load_config(cfg)

    def test_curve_missing_keys(self, tmp_path: Path) -> None:
        """Curve section with missing keys raises ConfigError naming the curve and keys."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.cpu]\n'
            'no_cooling_temp = 30\n'
        )
        with pytest.raises(ConfigError, match=r"\[thermal\.class\.cpu\].*missing"):
            load_config(cfg)

    def test_curve_unknown_key(self, tmp_path: Path) -> None:
        """Curve section with extra key raises ConfigError naming the key."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.cpu]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["cpu"]\n'
            'bogus = 42\n'
        )
        with pytest.raises(ConfigError, match=r"\[thermal\.class\.cpu\].*bogus"):
            load_config(cfg)

    def test_fan_unknown_key(self, tmp_path: Path) -> None:
        """Fan section with extra key raises ConfigError naming the key."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            'bogus = 42\n'
        )
        with pytest.raises(ConfigError, match=r"\[fans\.FAN1\].*bogus"):
            load_config(cfg)

    def test_sensor_override_unknown_key(self, tmp_path: Path) -> None:
        """Sensor override with extra key raises ConfigError naming the key."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.other]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[thermal.sensor.some_sensor]\n'
            'no_cooling_temp = 60\n'
            'bogus = 42\n'
        )
        with pytest.raises(ConfigError, match=r"\[thermal\.sensor\.some_sensor\].*bogus"):
            load_config(cfg)

    def test_fan_zones_string_instead_of_list(self, tmp_path: Path) -> None:
        """fan_zones as a string instead of list raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.cpu]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = "cpu"\n'
        )
        with pytest.raises(ConfigError, match="fan_zones.*list"):
            load_config(cfg)

    def test_sensor_override_fan_zones_string(self, tmp_path: Path) -> None:
        """fan_zones as a string in a sensor override raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.other]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[thermal.sensor.some_sensor]\n'
            'fan_zones = "peripheral"\n'
        )
        with pytest.raises(ConfigError, match="fan_zones.*list"):
            load_config(cfg)

    def test_non_integer_temp(self, tmp_path: Path) -> None:
        """Non-integer temperature raises ConfigError with section context."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.cpu]\n'
            'no_cooling_temp = "hot"\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["cpu"]\n'
        )
        with pytest.raises(ConfigError, match=r"\[thermal\.class\.cpu\].*no_cooling_temp"):
            load_config(cfg)

    def test_zone_in_curve_not_in_fans(self, tmp_path: Path) -> None:
        """Curve referencing a zone that no fan belongs to raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.cpu]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["cpu", "nonexistent"]\n'
            '\n'
            '[fans.CPU_FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.CPU_FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        with pytest.raises(ConfigError, match="nonexistent"):
            load_config(cfg)

    def test_fan_zone_not_in_any_curve(self, tmp_path: Path) -> None:
        """Fan in a zone that no thermal class drives raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            '[thermal.class.cpu]\n'
            'no_cooling_temp = 30\n'
            'max_cooling_temp = 80\n'
            'fan_zones = ["cpu"]\n'
            '\n'
            '[fans.CPU_FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.CPU_FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
            '\n'
            '[fans.SYS_FAN1]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.SYS_FAN1.setpoints]\n'
            '20 = 240\n'
            '100 = 1200\n'
        )
        with pytest.raises(ConfigError, match="peripheral.*no thermal class"):
            load_config(cfg)


# ---------------------------------------------------------------------------
# #### save_config
# ---------------------------------------------------------------------------

class TestSaveConfig:
    """Tests for save_config."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """Saving and reloading produces the same config."""
        cfg_path = tmp_path / "truefan.toml"
        cfg_path.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        original = load_config(cfg_path)

        updated_fans = MappingProxyType({
            "FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
        })
        updated = Config(
            poll_interval_seconds=original.poll_interval_seconds,
            curves=original.curves,
            fans=updated_fans,
        )
        save_config(cfg_path, updated)
        reloaded = load_config(cfg_path)
        assert reloaded.fans["FAN1"].zone == "cpu"
        assert dict(reloaded.fans["FAN1"].setpoints) == {30: 450, 100: 1500}

    def test_preserves_comments(self, tmp_path: Path) -> None:
        """Comments in the config file survive a save."""
        cfg_path = tmp_path / "truefan.toml"
        cfg_path.write_text(
            '# This is a user comment\n'
            'poll_interval_seconds = 5\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        config = load_config(cfg_path)
        save_config(cfg_path, config)
        content = cfg_path.read_text()
        assert "# This is a user comment" in content

    def test_preserves_user_thermal_sections(self, tmp_path: Path) -> None:
        """User-edited thermal class sections are not altered by save."""
        cfg_path = tmp_path / "truefan.toml"
        cfg_path.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[thermal.class.drive]\n'
            'no_cooling_temp = 25\n'
            'max_cooling_temp = 40\n'
            'fan_zones = ["peripheral"]\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        config = load_config(cfg_path)
        save_config(cfg_path, config)
        reloaded = load_config(cfg_path)
        assert reloaded.curves[SensorClass.DRIVE].no_cooling_temp == 25

    def test_save_to_new_file(self, tmp_path: Path) -> None:
        """Saving to a nonexistent file creates it."""
        cfg_path = tmp_path / "new.toml"
        config = Config(
            poll_interval_seconds=5,
            curves=DEFAULT_CURVES,
            fans=MappingProxyType({
                "CPU_FAN1": FanConfig(
                    zone="cpu",
                    setpoints=MappingProxyType({25: 320, 100: 1500}),
                ),
                "SYS_FAN1": FanConfig(
                    zone="peripheral",
                    setpoints=MappingProxyType({25: 300, 100: 1200}),
                ),
            }),
        )
        save_config(cfg_path, config)
        reloaded = load_config(cfg_path)
        assert reloaded.poll_interval_seconds == 5
        assert dict(reloaded.fans["CPU_FAN1"].setpoints) == {25: 320, 100: 1500}

    def test_save_to_new_file_sorts_classes(self, tmp_path: Path) -> None:
        """Thermal class sections are written in alphabetical order."""
        cfg_path = tmp_path / "new.toml"
        config = Config(
            poll_interval_seconds=5,
            curves=DEFAULT_CURVES,
            fans=MappingProxyType({
                "CPU_FAN1": FanConfig(
                    zone="cpu",
                    setpoints=MappingProxyType({25: 320, 100: 1500}),
                ),
                "SYS_FAN1": FanConfig(
                    zone="peripheral",
                    setpoints=MappingProxyType({25: 300, 100: 1200}),
                ),
            }),
        )
        save_config(cfg_path, config)
        content = cfg_path.read_text()
        # Find positions of each class section
        positions = []
        for cls in sorted(DEFAULT_CURVES, key=lambda c: c.value):
            pos = content.find(f"[thermal.class.{cls.value}]")
            assert pos >= 0, f"Missing [thermal.class.{cls.value}]"
            positions.append(pos)
        assert positions == sorted(positions), "Thermal class sections not in alphabetical order"

    def test_add_new_fan(self, tmp_path: Path) -> None:
        """Adding a fan to config creates a new section in the file."""
        cfg_path = tmp_path / "truefan.toml"
        cfg_path.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
        )
        original = load_config(cfg_path)
        updated_fans = dict(original.fans)
        updated_fans["FAN2"] = FanConfig(
            zone="peripheral",
            setpoints=MappingProxyType({20: 280, 100: 1450}),
        )
        updated = Config(
            poll_interval_seconds=original.poll_interval_seconds,
            curves=original.curves,
            fans=MappingProxyType(updated_fans),
        )
        save_config(cfg_path, updated)
        reloaded = load_config(cfg_path)
        assert "FAN1" in reloaded.fans
        assert "FAN2" in reloaded.fans
        assert dict(reloaded.fans["FAN2"].setpoints) == {20: 280, 100: 1450}

    def test_remove_fan(self, tmp_path: Path) -> None:
        """Removing a fan from config removes its section from the file."""
        cfg_path = tmp_path / "truefan.toml"
        cfg_path.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[fans.FAN1]\n'
            'zone = "cpu"\n'
            '\n'
            '[fans.FAN1.setpoints]\n'
            '25 = 320\n'
            '100 = 1500\n'
            '\n'
            '[fans.FAN2]\n'
            'zone = "peripheral"\n'
            '\n'
            '[fans.FAN2.setpoints]\n'
            '20 = 280\n'
            '100 = 1450\n'
        )
        original = load_config(cfg_path)
        updated_fans = {k: v for k, v in original.fans.items() if k != "FAN2"}
        updated = Config(
            poll_interval_seconds=original.poll_interval_seconds,
            curves=original.curves,
            fans=MappingProxyType(updated_fans),
        )
        save_config(cfg_path, updated)
        reloaded = load_config(cfg_path)
        assert "FAN1" in reloaded.fans
        assert "FAN2" not in reloaded.fans

    def test_remove_curve(self, tmp_path: Path) -> None:
        """Saving with a curve removed drops it from the file."""
        cfg_path = tmp_path / "truefan.toml"
        fans = MappingProxyType({
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({25: 320, 100: 1500}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({25: 300, 100: 1200}),
            ),
        })
        config = Config(
            poll_interval_seconds=5,
            curves=MappingProxyType({
                SensorClass.CPU: DEFAULT_CURVES[SensorClass.CPU],
                SensorClass.DRIVE: DEFAULT_CURVES[SensorClass.DRIVE],
            }),
            fans=fans,
        )
        save_config(cfg_path, config)
        # Now save again without the DRIVE curve.
        updated = Config(
            poll_interval_seconds=5,
            curves=MappingProxyType({
                SensorClass.CPU: DEFAULT_CURVES[SensorClass.CPU],
            }),
            fans=fans,
        )
        save_config(cfg_path, updated)
        reloaded = load_config(cfg_path)
        assert SensorClass.CPU in reloaded.curves
        assert SensorClass.DRIVE not in reloaded.curves


# ---------------------------------------------------------------------------
# #### validate_config
# ---------------------------------------------------------------------------


def _make_config(
    fans: dict[str, FanConfig] | None = None,
    sensor_overrides: dict[str, "SensorOverride"] | None = None,
) -> Config:
    """Build a Config with sensible defaults for validation tests."""
    if fans is None:
        fans = {
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({20: 240, 100: 1200}),
            ),
        }
    return Config(
        poll_interval_seconds=5,
        curves=MappingProxyType({
            SensorClass.CPU: Curve(
                no_cooling_temp=30, max_cooling_temp=80,
                fan_zones=frozenset({"cpu", "peripheral"}),
            ),
        }),
        fans=MappingProxyType(fans),
        sensor_overrides=MappingProxyType(sensor_overrides or {}),
    )


def _make_sim_for_fans(
    fan_names: dict[str, str],
) -> FanSimulator:
    """Create a FanSimulator with the given {name: zone} fans."""
    sim = FanSimulator(fans={
        name: {"max_rpm": 1500} for name in fan_names
    })
    for name, zone in fan_names.items():
        sim.set_fan_zone(name, zone)
    return sim


class TestValidateConfig:
    """Tests for validate_config."""

    def test_all_fans_match(self) -> None:
        """No errors when config fans match hardware exactly."""
        config = _make_config()
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu", "SYS_FAN1": "peripheral"})
        readings = [
            SensorReading(name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0),
        ]
        errors = validate_config(config, sim, readings)
        assert errors == []

    def test_config_fan_not_in_hardware(self) -> None:
        """Error when config has a fan that hardware doesn't."""
        config = _make_config()
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu"})
        errors = validate_config(config, sim, [])
        assert any("SYS_FAN1" in e for e in errors)

    def test_hardware_fan_not_in_config(self) -> None:
        """Error when hardware has a fan that config doesn't."""
        config = _make_config(fans={
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
        })
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu", "SYS_FAN1": "peripheral"})
        errors = validate_config(config, sim, [])
        assert any("SYS_FAN1" in e for e in errors)

    def test_zone_mismatch(self) -> None:
        """Error when config and hardware disagree on a fan's zone."""
        config = _make_config(fans={
            "CPU_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({20: 240, 100: 1200}),
            ),
        })
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu", "SYS_FAN1": "peripheral"})
        errors = validate_config(config, sim, [])
        assert any("CPU_FAN1" in e and "cpu" in e and "peripheral" in e for e in errors)

    def test_multiple_errors(self) -> None:
        """All mismatches reported, not just the first."""
        config = _make_config(fans={
            "CPU_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
        })
        # CPU_FAN1 zone mismatch + SYS_FAN2 in hardware but not config
        # + SYS_FAN1 in config... wait, SYS_FAN1 is not in this config.
        # Let me use: config has CPU_FAN1 (wrong zone), hardware has CPU_FAN1 + SYS_FAN2.
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu", "SYS_FAN2": "peripheral"})
        errors = validate_config(config, sim, [])
        # zone mismatch on CPU_FAN1, SYS_FAN1 missing from hardware, SYS_FAN2 not in config
        assert len(errors) >= 2

    def test_sensor_override_unknown_sensor(self) -> None:
        """Error when sensor override references a sensor not in readings."""
        from truefan.config import SensorOverride

        config = _make_config(sensor_overrides={
            "nonexistent_sensor": SensorOverride(no_cooling_temp=50),
        })
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu", "SYS_FAN1": "peripheral"})
        readings = [
            SensorReading(name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0),
        ]
        errors = validate_config(config, sim, readings)
        assert any("nonexistent_sensor" in e for e in errors)

    def test_sensor_override_valid(self) -> None:
        """No error when sensor override references a real sensor."""
        from truefan.config import SensorOverride

        config = _make_config(sensor_overrides={
            "ipmi_CPU_Temp": SensorOverride(no_cooling_temp=50),
        })
        sim = _make_sim_for_fans({"CPU_FAN1": "cpu", "SYS_FAN1": "peripheral"})
        readings = [
            SensorReading(name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0),
        ]
        errors = validate_config(config, sim, readings)
        assert errors == []
