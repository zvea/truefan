"""Tests for truefan.commands.check."""

from pathlib import Path
from types import MappingProxyType

import pytest

from unittest.mock import patch

from tests.mocks import FanSimulator
from truefan.bmc import BmcConnection
from truefan.commands.check import run_check
from truefan.config import Config, Curve, FanConfig, save_config
from truefan.sensors import SensorClass


def _write_valid_config(path: Path) -> None:
    """Write a config that matches _make_matching_sim."""
    config = Config(
        poll_interval_seconds=5,
        curves=MappingProxyType({
            SensorClass.CPU: Curve(
                no_cooling_temp=30, max_cooling_temp=80,
                fan_zones=frozenset({"cpu", "peripheral"}),
            ),
        }),
        fans=MappingProxyType({
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({20: 240, 100: 1200}),
            ),
        }),
    )
    save_config(path, config)


def _make_matching_sim() -> FanSimulator:
    """Create a FanSimulator that matches _write_valid_config."""
    sim = FanSimulator(fans={
        "CPU_FAN1": {"max_rpm": 1500},
        "SYS_FAN1": {"max_rpm": 1200},
    })
    sim.set_fan_zone("CPU_FAN1", "cpu")
    sim.set_fan_zone("SYS_FAN1", "peripheral")
    return sim


# ---------------------------------------------------------------------------
# #### run_check
# ---------------------------------------------------------------------------

class TestRunCheck:
    """Tests for run_check."""

    @patch("truefan.commands.check.check_ipmi_access", return_value=None)
    def test_valid_config_and_hardware(
        self, mock_ipmi, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints 'Config OK' and exits 0 when everything matches."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        run_check(cfg, syntax_only=False, conn=sim)
        assert "Config OK" in capsys.readouterr().out

    def test_malformed_toml(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints TOML error and exits 1 on broken syntax."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("[invalid\n")
        with pytest.raises(SystemExit) as exc_info:
            run_check(cfg, syntax_only=False, conn=_make_matching_sim())
        assert exc_info.value.code == 1
        assert "Malformed TOML" in capsys.readouterr().err

    def test_unrecognized_config_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints the bad key name and exits 1."""
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
        with pytest.raises(SystemExit) as exc_info:
            run_check(cfg, syntax_only=False, conn=_make_matching_sim())
        assert exc_info.value.code == 1
        assert "fnas" in capsys.readouterr().err

    @patch("truefan.commands.check.check_ipmi_access", return_value=None)
    def test_fan_mismatch(
        self, mock_ipmi, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints missing fan name and exits 1."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = FanSimulator(fans={"CPU_FAN1": {"max_rpm": 1500}})
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(SystemExit) as exc_info:
            run_check(cfg, syntax_only=False, conn=sim)
        assert exc_info.value.code == 1
        assert "SYS_FAN1" in capsys.readouterr().err

    def test_syntax_only_valid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints 'Config OK' with --syntax-only and valid config."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        run_check(cfg, syntax_only=True)
        assert "Config OK" in capsys.readouterr().out

    def test_syntax_only_broken(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints error and exits 1 with --syntax-only and broken config."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("[invalid\n")
        with pytest.raises(SystemExit) as exc_info:
            run_check(cfg, syntax_only=True)
        assert exc_info.value.code == 1
        assert "Malformed TOML" in capsys.readouterr().err

    def test_syntax_only_never_touches_bmc(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--syntax-only must not contact BMC at all, so it works without one."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)

        class NoBmc(BmcConnection):
            """BmcConnection that fails on any call."""

            def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
                raise AssertionError("BMC should not be contacted")

            def set_sensor_thresholds(
                self, sensor_name: str,
                lower: tuple[int, int, int], upper: tuple[int, int, int],
            ) -> None:
                raise AssertionError("BMC should not be contacted")

            def list_fans(self) -> list[tuple[str, int | None]]:
                raise AssertionError("BMC should not be contacted")

            def list_temperature_sensors(self) -> list:
                raise AssertionError("BMC should not be contacted")

            def read_sel(self, last_n: int = 20) -> list:
                raise AssertionError("BMC should not be contacted")

        run_check(cfg, syntax_only=True, conn=NoBmc())
        assert "Config OK" in capsys.readouterr().out
