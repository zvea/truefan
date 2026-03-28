"""Tests for truefan.config."""

from pathlib import Path
from types import MappingProxyType

import pytest

from truefan.config import (
    DEFAULT_CURVES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    Config,
    ConfigError,
    Curve,
    FanConfig,
    load_config,
    save_config,
)
from truefan.sensors import SensorClass


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
        """A curve override replaces the default for that class."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[curves.drive]\n'
            'temp_low = 25\n'
            'temp_high = 40\n'
            'duty_low = 30\n'
            'duty_high = 90\n'
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
        assert drive_curve.temp_low == 25
        assert drive_curve.temp_high == 40
        assert drive_curve.duty_low == 30
        assert drive_curve.duty_high == 90
        assert drive_curve.fan_zones == frozenset({"peripheral"})

    def test_partial_curve_overrides(self, tmp_path: Path) -> None:
        """Only explicitly listed sensor classes have curves."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[curves.cpu]\n'
            'temp_low = 40\n'
            'temp_high = 90\n'
            'duty_low = 30\n'
            'duty_high = 100\n'
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
        assert config.curves[SensorClass.CPU].temp_low == 40
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

    def test_temp_low_exceeds_temp_high(self, tmp_path: Path) -> None:
        """Curve with temp_low > temp_high raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[curves.drive]\n'
            'temp_low = 50\n'
            'temp_high = 30\n'
            'duty_low = 25\n'
            'duty_high = 100\n'
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

    def test_unknown_sensor_class(self, tmp_path: Path) -> None:
        """Curve for an unknown sensor class raises ConfigError."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[curves.unknown]\n'
            'temp_low = 30\n'
            'temp_high = 50\n'
            'duty_low = 25\n'
            'duty_high = 100\n'
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

    def test_preserves_user_curve_sections(self, tmp_path: Path) -> None:
        """User-edited curve sections are not altered by save."""
        cfg_path = tmp_path / "truefan.toml"
        cfg_path.write_text(
            'poll_interval_seconds = 5\n'
            '\n'
            '[curves.drive]\n'
            'temp_low = 25\n'
            'temp_high = 40\n'
            'duty_low = 30\n'
            'duty_high = 90\n'
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
        assert reloaded.curves[SensorClass.DRIVE].temp_low == 25
        assert reloaded.curves[SensorClass.DRIVE].duty_low == 30

    def test_save_to_new_file(self, tmp_path: Path) -> None:
        """Saving to a nonexistent file creates it."""
        cfg_path = tmp_path / "new.toml"
        config = Config(
            poll_interval_seconds=5,
            curves=DEFAULT_CURVES,
            fans=MappingProxyType({
                "FAN1": FanConfig(
                    zone="cpu",
                    setpoints=MappingProxyType({25: 320, 100: 1500}),
                ),
            }),
        )
        save_config(cfg_path, config)
        reloaded = load_config(cfg_path)
        assert reloaded.poll_interval_seconds == 5
        assert dict(reloaded.fans["FAN1"].setpoints) == {25: 320, 100: 1500}

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
        config = Config(
            poll_interval_seconds=5,
            curves=MappingProxyType({
                SensorClass.CPU: DEFAULT_CURVES[SensorClass.CPU],
                SensorClass.DRIVE: DEFAULT_CURVES[SensorClass.DRIVE],
            }),
            fans=MappingProxyType({
                "FAN1": FanConfig(
                    zone="cpu",
                    setpoints=MappingProxyType({25: 320, 100: 1500}),
                ),
            }),
        )
        save_config(cfg_path, config)
        # Now save again without the DRIVE curve.
        updated = Config(
            poll_interval_seconds=5,
            curves=MappingProxyType({
                SensorClass.CPU: DEFAULT_CURVES[SensorClass.CPU],
            }),
            fans=config.fans,
        )
        save_config(cfg_path, updated)
        reloaded = load_config(cfg_path)
        assert SensorClass.CPU in reloaded.curves
        assert SensorClass.DRIVE not in reloaded.curves
