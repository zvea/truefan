"""Tests for truefan.commands.logs."""

from unittest.mock import patch

from truefan.commands.logs import run_logs


# ---------------------------------------------------------------------------
# #### run_logs
# ---------------------------------------------------------------------------

class TestRunLogs:
    """Tests for run_logs."""

    @patch("truefan.commands.logs.os.execvp")
    def test_default_invocation(self, mock_execvp: object) -> None:
        """With no extra args, calls journalctl -t truefan."""
        run_logs([])
        mock_execvp.assert_called_once_with(  # type: ignore[union-attr]
            "journalctl", ["journalctl", "-t", "truefan"],
        )

    @patch("truefan.commands.logs.os.execvp")
    def test_forwards_extra_args(self, mock_execvp: object) -> None:
        """Extra arguments are appended to the journalctl command."""
        run_logs(["-f", "-n", "50"])
        mock_execvp.assert_called_once_with(  # type: ignore[union-attr]
            "journalctl", ["journalctl", "-t", "truefan", "-f", "-n", "50"],
        )
