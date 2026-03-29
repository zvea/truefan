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
