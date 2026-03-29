"""Tests for truefan.main."""

from pathlib import Path

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
        # "help" appears in the -h/--help option but not in the subcommand list.
        # The subcommand list is in the {init,run,...} line.
        lines = [l for l in out.splitlines() if l.strip().startswith("help")]
        # Only the -h/--help line should match, not a subcommand entry.
        for line in lines:
            assert "--help" in line or "-h" in line
