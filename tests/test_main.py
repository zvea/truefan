"""Tests for truefan.main."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from truefan.main import main


# ---------------------------------------------------------------------------
# #### --config position
# ---------------------------------------------------------------------------

class TestConfigPosition:
    """--config works before or after the subcommand."""

    def test_config_before_subcommand(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """truefan --config PATH check --syntax-only succeeds."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("poll_interval_seconds = 5\n")
        main(["--config", str(cfg), "check", "--syntax-only"])
        assert "Config OK" in capsys.readouterr().out

    def test_config_after_subcommand(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """truefan check --config PATH --syntax-only succeeds."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("poll_interval_seconds = 5\n")
        main(["check", "--config", str(cfg), "--syntax-only"])
        assert "Config OK" in capsys.readouterr().out

    def test_subcommand_config_wins(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When --config given in both positions, the subcommand value wins."""
        bad = tmp_path / "bad.toml"
        bad.write_text("[invalid\n")
        good = tmp_path / "good.toml"
        good.write_text("poll_interval_seconds = 5\n")
        # Parent gets bad, subcommand gets good — good should win.
        main(["--config", str(bad), "check", "--config", str(good), "--syntax-only"])
        assert "Config OK" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# #### help subcommand
# ---------------------------------------------------------------------------

class TestHelp:
    """Tests for the help subcommand."""

    def test_help_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'truefan help' prints the help page."""
        main(["help"])
        out = capsys.readouterr().out
        assert "Fan control daemon" in out
        assert "init" in out

    def test_help_not_in_subcommand_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'help' does not appear as a listed subcommand."""
        main(["help"])
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if l.strip().startswith("help")]
        for line in lines:
            assert "--help" in line or "-h" in line


# ---------------------------------------------------------------------------
# #### subcommand recognition
# ---------------------------------------------------------------------------

class TestSubcommandRecognition:
    """Tests for subcommand dispatch."""

    def test_run_is_not_recognized(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'truefan run' is no longer a valid subcommand."""
        with pytest.raises(SystemExit):
            main(["run"])

    @patch("truefan.commands.start.run_start")
    def test_start_dispatches(self, mock_run_start: MagicMock, tmp_path: Path) -> None:
        """'truefan start' dispatches to run_start."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        main(["start", "--config", str(cfg)])
        mock_run_start.assert_called_once()

    @patch("truefan.commands.start.run_start")
    def test_start_foreground_flag(self, mock_run_start: MagicMock, tmp_path: Path) -> None:
        """'truefan start --foreground' passes foreground=True."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        main(["start", "--foreground", "--config", str(cfg)])
        _, kwargs = mock_run_start.call_args
        assert kwargs.get("foreground") is True

    @patch("truefan.commands.stop.run_stop")
    def test_stop_dispatches(self, mock_run_stop: MagicMock) -> None:
        """'truefan stop' dispatches to run_stop."""
        main(["stop"])
        mock_run_stop.assert_called_once()

    @patch("truefan.commands.start.run_start")
    @patch("truefan.commands.stop.run_stop")
    def test_restart_calls_stop_then_start(
        self, mock_run_stop: MagicMock, mock_run_start: MagicMock,
        tmp_path: Path,
    ) -> None:
        """'truefan restart' calls stop (tolerating not running) then start."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        main(["restart", "--config", str(cfg)])
        mock_run_stop.assert_called_once()
        mock_run_start.assert_called_once()

    @patch("truefan.commands.start.run_start")
    @patch("truefan.commands.stop.run_stop", side_effect=SystemExit(1))
    def test_restart_tolerates_no_daemon(
        self, mock_run_stop: MagicMock, mock_run_start: MagicMock,
        tmp_path: Path,
    ) -> None:
        """'truefan restart' starts even if stop fails (no daemon running)."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        main(["restart", "--config", str(cfg)])
        mock_run_start.assert_called_once()

    @patch("truefan.commands.start.run_start")
    def test_restart_foreground_flag(
        self, mock_run_start: MagicMock, tmp_path: Path,
    ) -> None:
        """'truefan restart --foreground' passes foreground to start."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        with patch("truefan.commands.stop.run_stop"):
            main(["restart", "--foreground", "--config", str(cfg)])
        _, kwargs = mock_run_start.call_args
        assert kwargs.get("foreground") is True

    @patch("truefan.commands.init.run_init")
    def test_init_dispatches(self, mock: MagicMock, tmp_path: Path) -> None:
        """'truefan init' dispatches to run_init."""
        cfg = tmp_path / "truefan.toml"
        main(["init", "--config", str(cfg)])
        mock.assert_called_once()

    @patch("truefan.commands.recalibrate.run_recalibrate")
    def test_recalibrate_dispatches(self, mock: MagicMock, tmp_path: Path) -> None:
        """'truefan recalibrate' dispatches to run_recalibrate."""
        cfg = tmp_path / "truefan.toml"
        main(["recalibrate", "--config", str(cfg)])
        mock.assert_called_once()

    @patch("truefan.commands.status.run_status")
    def test_status_dispatches(self, mock: MagicMock) -> None:
        """'truefan status' dispatches to run_status."""
        main(["status"])
        mock.assert_called_once()

    @patch("truefan.commands.sensors.run_sensors")
    def test_sensors_dispatches(self, mock: MagicMock) -> None:
        """'truefan sensors' dispatches to run_sensors."""
        main(["sensors"])
        mock.assert_called_once()

    @patch("truefan.commands.reload.run_reload")
    def test_reload_dispatches(self, mock: MagicMock, tmp_path: Path) -> None:
        """'truefan reload' dispatches to run_reload."""
        cfg = tmp_path / "truefan.toml"
        main(["reload", "--config", str(cfg)])
        mock.assert_called_once()

    @patch("truefan.commands.check.run_check")
    def test_check_dispatches(self, mock: MagicMock, tmp_path: Path) -> None:
        """'truefan check' dispatches to run_check."""
        cfg = tmp_path / "truefan.toml"
        main(["check", "--config", str(cfg)])
        mock.assert_called_once()

    @patch("truefan.commands.logs.run_logs")
    def test_logs_dispatches(self, mock: MagicMock) -> None:
        """'truefan logs' dispatches to run_logs."""
        main(["logs"])
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# #### logs arg forwarding
# ---------------------------------------------------------------------------

class TestLogsArgForwarding:
    """Tests for logs argument splitting."""

    @patch("truefan.commands.logs.run_logs")
    def test_extra_args_forwarded(self, mock: MagicMock) -> None:
        """Extra args after 'logs' are forwarded to run_logs."""
        main(["logs", "-f", "-n", "50"])
        mock.assert_called_once_with(["-f", "-n", "50"])

    @patch("truefan.commands.logs.run_logs")
    def test_no_extra_args(self, mock: MagicMock) -> None:
        """'truefan logs' with no extra args passes an empty list."""
        main(["logs"])
        mock.assert_called_once_with([])


# ---------------------------------------------------------------------------
# #### no subcommand
# ---------------------------------------------------------------------------

class TestNoSubcommand:
    """Tests for invocation with no subcommand."""

    def test_no_args_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'truefan' with no subcommand prints help."""
        main([])
        out = capsys.readouterr().out
        assert "Fan control daemon" in out


# ---------------------------------------------------------------------------
# #### argv=None fallback
# ---------------------------------------------------------------------------

class TestArgvNone:
    """Tests for main(None) falling back to sys.argv."""

    @patch("truefan.commands.sensors.run_sensors")
    def test_uses_sys_argv(self, mock: MagicMock) -> None:
        """main(None) reads from sys.argv."""
        import sys
        with patch.object(sys, "argv", ["truefan", "sensors"]):
            main(None)
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# #### error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Tests for exception handling in main()."""

    def test_exception_prints_to_stderr(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An exception from a subcommand prints to stderr and exits 1."""
        with patch("truefan.commands.sensors.run_sensors", side_effect=RuntimeError("boom")):
            with pytest.raises(SystemExit) as exc_info:
                main(["sensors"])
            assert exc_info.value.code == 1
        assert "boom" in capsys.readouterr().err

    def test_keyboard_interrupt_exits_130(self) -> None:
        """KeyboardInterrupt exits with code 130."""
        with patch("truefan.commands.sensors.run_sensors", side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit) as exc_info:
                main(["sensors"])
            assert exc_info.value.code == 130
