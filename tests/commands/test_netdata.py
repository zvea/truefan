"""Tests for truefan.commands.netdata."""

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from truefan.commands.netdata import (
    _packaged_content,
    check_netdata_config,
    detect_container,
    run_check,
    run_install,
    run_uninstall,
)


def _mock_docker_run(responses: dict[tuple[str, ...], str | Exception]) -> MagicMock:
    """Build a side_effect for subprocess.run that dispatches on docker args.

    *responses* maps tuples of docker args (excluding 'docker' itself) to
    either stdout strings or exceptions to raise.
    """
    def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd[0] == "docker"
        key = tuple(cmd[1:])
        for pattern, result in responses.items():
            if key[:len(pattern)] == pattern:
                if isinstance(result, Exception):
                    raise result
                return subprocess.CompletedProcess(cmd, 0, stdout=result, stderr="")
        raise subprocess.CalledProcessError(1, cmd, stderr=f"unexpected: {cmd}")

    return MagicMock(side_effect=side_effect)


# ---------------------------------------------------------------------------
# #### _packaged_content
# ---------------------------------------------------------------------------

class TestPackagedContent:
    """Tests for _packaged_content."""

    def test_reads_statsd_config(self) -> None:
        """The statsd config file is readable from the package."""
        content = _packaged_content("statsd.d/truefan.conf")
        assert "truefan" in content
        assert len(content) > 0

    def test_reads_alerts_config(self) -> None:
        """The alerts config file is readable from the package."""
        content = _packaged_content("health.d/truefan_alerts.conf")
        assert "truefan" in content
        assert len(content) > 0


# ---------------------------------------------------------------------------
# #### detect_container
# ---------------------------------------------------------------------------

class TestDetectContainer:
    """Tests for detect_container."""

    @patch("truefan.commands.netdata.subprocess.run")
    def test_explicit_container_running(self, mock_run: MagicMock) -> None:
        """Returns the container name when it exists and is running."""
        mock_run.side_effect = _mock_docker_run({
            ("info",): "",
            ("inspect", "-f"): "running\n",
        }).side_effect
        assert detect_container("my-netdata") == "my-netdata"

    @patch("truefan.commands.netdata.subprocess.run")
    def test_explicit_container_not_found(self, mock_run: MagicMock) -> None:
        """Exits 1 when the named container does not exist."""
        mock_run.side_effect = _mock_docker_run({
            ("info",): "",
        }).side_effect
        with pytest.raises(SystemExit) as exc_info:
            detect_container("ghost")
        assert exc_info.value.code == 1

    @patch("truefan.commands.netdata.subprocess.run")
    def test_explicit_container_not_running(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 with clear message when the container is stopped."""
        mock_run.side_effect = _mock_docker_run({
            ("info",): "",
            ("inspect", "-f"): "exited\n",
        }).side_effect
        with pytest.raises(SystemExit) as exc_info:
            detect_container("my-netdata")
        assert exc_info.value.code == 1
        assert "exited" in capsys.readouterr().err

    @patch("truefan.commands.netdata.subprocess.run")
    def test_auto_detect_single(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Auto-detects the single running Netdata container."""
        mock_run.side_effect = _mock_docker_run({
            ("info",): "",
            ("ps",): "netdata\nredis\n",
        }).side_effect
        assert detect_container(None) == "netdata"
        assert "Detected" in capsys.readouterr().out

    @patch("truefan.commands.netdata.subprocess.run")
    def test_auto_detect_none(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 when no running container has 'netdata' in its name."""
        mock_run.side_effect = _mock_docker_run({
            ("info",): "",
            ("ps",): "redis\npostgres\n",
        }).side_effect
        with pytest.raises(SystemExit) as exc_info:
            detect_container(None)
        assert exc_info.value.code == 1
        assert "--container" in capsys.readouterr().err

    @patch("truefan.commands.netdata.subprocess.run")
    def test_auto_detect_multiple(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 when multiple containers match 'netdata'."""
        mock_run.side_effect = _mock_docker_run({
            ("info",): "",
            ("ps",): "netdata-prod\nnetdata-dev\n",
        }).side_effect
        with pytest.raises(SystemExit) as exc_info:
            detect_container(None)
        assert exc_info.value.code == 1
        assert "multiple" in capsys.readouterr().err.lower()

    @patch("truefan.commands.netdata.subprocess.run")
    def test_docker_not_available(
        self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 with clear message when docker is not found."""
        mock_run.side_effect = FileNotFoundError("docker")
        with pytest.raises(SystemExit) as exc_info:
            detect_container(None)
        assert exc_info.value.code == 1
        assert "docker" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# #### run_check
# ---------------------------------------------------------------------------

class TestRunCheck:
    """Tests for run_check."""

    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    @patch("truefan.commands.netdata._container_file_content")
    def test_all_up_to_date(
        self, mock_content: MagicMock, mock_detect: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 0 when both configs match packaged versions."""
        mock_content.side_effect = lambda _c, path: _packaged_content(
            "statsd.d/truefan.conf" if "statsd" in path
            else "health.d/truefan_alerts.conf"
        )
        run_check("netdata")
        out = capsys.readouterr().out
        assert "up to date" in out

    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    @patch("truefan.commands.netdata._container_file_content", return_value=None)
    def test_missing_configs(
        self, mock_content: MagicMock, mock_detect: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 when configs are missing from the container."""
        with pytest.raises(SystemExit) as exc_info:
            run_check("netdata")
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "missing" in out

    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    @patch("truefan.commands.netdata._container_file_content", return_value="old content")
    def test_outdated_configs(
        self, mock_content: MagicMock, mock_detect: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 when configs differ from packaged versions."""
        with pytest.raises(SystemExit) as exc_info:
            run_check("netdata")
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "outdated" in out


# ---------------------------------------------------------------------------
# #### run_install
# ---------------------------------------------------------------------------

class TestRunInstall:
    """Tests for run_install."""

    @patch("truefan.commands.netdata._restart_and_wait")
    @patch("truefan.commands.netdata._is_persistent", return_value=True)
    @patch("truefan.commands.netdata._docker_ok", return_value=None)
    @patch("truefan.commands.netdata._container_file_content", return_value=None)
    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    @patch("truefan.commands.netdata.subprocess.run")
    def test_installs_missing_configs(
        self, mock_run: MagicMock, mock_detect: MagicMock,
        mock_content: MagicMock, mock_docker_ok: MagicMock,
        mock_persistent: MagicMock, mock_restart: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Copies configs when they are missing and restarts."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        run_install("netdata")
        out = capsys.readouterr().out
        assert "Installed" in out
        mock_restart.assert_called_once()

    @patch("truefan.commands.netdata._restart_and_wait")
    @patch("truefan.commands.netdata._container_file_content")
    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    def test_skips_up_to_date(
        self, mock_detect: MagicMock, mock_content: MagicMock,
        mock_restart: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Skips files already up to date and does not restart."""
        mock_content.side_effect = lambda _c, path: _packaged_content(
            "statsd.d/truefan.conf" if "statsd" in path
            else "health.d/truefan_alerts.conf"
        )
        run_install("netdata")
        out = capsys.readouterr().out
        assert "already up to date" in out.lower()
        mock_restart.assert_not_called()

    @patch("truefan.commands.netdata._restart_and_wait")
    @patch("truefan.commands.netdata._is_persistent", return_value=True)
    @patch("truefan.commands.netdata._docker_ok", return_value=None)
    @patch("truefan.commands.netdata._container_file_content")
    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    @patch("truefan.commands.netdata.subprocess.run")
    def test_force_overwrites(
        self, mock_run: MagicMock, mock_detect: MagicMock,
        mock_content: MagicMock, mock_docker_ok: MagicMock,
        mock_persistent: MagicMock, mock_restart: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With --force, overwrites even when content matches."""
        # Return matching content — force should still install.
        mock_content.side_effect = lambda _c, path: _packaged_content(
            "statsd.d/truefan.conf" if "statsd" in path
            else "health.d/truefan_alerts.conf"
        )
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        run_install("netdata", force=True)
        out = capsys.readouterr().out
        assert "Installed" in out
        mock_restart.assert_called_once()

    @patch("truefan.commands.netdata._restart_and_wait")
    @patch("truefan.commands.netdata._is_persistent", return_value=False)
    @patch("truefan.commands.netdata._docker_ok", return_value=None)
    @patch("truefan.commands.netdata._container_file_content", return_value=None)
    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    @patch("truefan.commands.netdata.subprocess.run")
    def test_warns_ephemeral_storage(
        self, mock_run: MagicMock, mock_detect: MagicMock,
        mock_content: MagicMock, mock_docker_ok: MagicMock,
        mock_persistent: MagicMock, mock_restart: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Warns when the destination is not on a persistent mount."""
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        run_install("netdata")
        err = capsys.readouterr().err
        assert "host mount" in err


# ---------------------------------------------------------------------------
# #### run_uninstall
# ---------------------------------------------------------------------------

class TestRunUninstall:
    """Tests for run_uninstall."""

    @patch("truefan.commands.netdata._restart_and_wait")
    @patch("truefan.commands.netdata._docker")
    @patch("truefan.commands.netdata._docker_ok")
    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    def test_removes_existing_configs(
        self, mock_detect: MagicMock, mock_docker_ok: MagicMock,
        mock_docker: MagicMock, mock_restart: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Removes config files and restarts the container."""
        # test -f succeeds (file exists).
        mock_docker_ok.return_value = subprocess.CompletedProcess([], 0)
        mock_docker.return_value = subprocess.CompletedProcess([], 0)
        run_uninstall("netdata")
        out = capsys.readouterr().out
        assert "Removed" in out
        mock_restart.assert_called_once()

    @patch("truefan.commands.netdata._restart_and_wait")
    @patch("truefan.commands.netdata._docker_ok", return_value=None)
    @patch("truefan.commands.netdata.detect_container", return_value="netdata")
    def test_nothing_to_remove(
        self, mock_detect: MagicMock, mock_docker_ok: MagicMock,
        mock_restart: MagicMock, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Prints 'Nothing to remove' when files are already absent."""
        run_uninstall("netdata")
        out = capsys.readouterr().out
        assert "Nothing to remove" in out
        mock_restart.assert_not_called()


# ---------------------------------------------------------------------------
# #### check_netdata_config
# ---------------------------------------------------------------------------

class TestCheckNetdataConfig:
    """Tests for check_netdata_config (daemon startup check)."""

    @patch("truefan.commands.netdata._docker")
    def test_docker_unavailable(self, mock_docker: MagicMock) -> None:
        """Returns empty list when Docker is not available."""
        mock_docker.side_effect = RuntimeError("docker not found")
        assert check_netdata_config() == []

    @patch("truefan.commands.netdata._docker")
    def test_no_netdata_container(self, mock_docker: MagicMock) -> None:
        """Returns empty list when no Netdata container is running."""
        # First call is docker info (succeeds), second is docker ps.
        mock_docker.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=""),
            subprocess.CompletedProcess([], 0, stdout="redis\npostgres\n"),
        ]
        assert check_netdata_config() == []

    @patch("truefan.commands.netdata._container_file_content")
    @patch("truefan.commands.netdata._docker")
    def test_configs_up_to_date(
        self, mock_docker: MagicMock, mock_content: MagicMock,
    ) -> None:
        """Returns empty list when configs match packaged versions."""
        mock_docker.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=""),
            subprocess.CompletedProcess([], 0, stdout="netdata\n"),
        ]
        mock_content.side_effect = lambda _c, path: _packaged_content(
            "statsd.d/truefan.conf" if "statsd" in path
            else "health.d/truefan_alerts.conf"
        )
        assert check_netdata_config() == []

    @patch("truefan.commands.netdata._container_file_content", return_value=None)
    @patch("truefan.commands.netdata._docker")
    def test_configs_missing(
        self, mock_docker: MagicMock, mock_content: MagicMock,
    ) -> None:
        """Returns warnings when configs are missing."""
        mock_docker.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=""),
            subprocess.CompletedProcess([], 0, stdout="netdata\n"),
        ]
        warnings = check_netdata_config()
        assert len(warnings) == 2
        assert all("missing" in w for w in warnings)
        assert all("truefan netdata install" in w for w in warnings)

    @patch("truefan.commands.netdata._container_file_content", return_value="old")
    @patch("truefan.commands.netdata._docker")
    def test_configs_outdated(
        self, mock_docker: MagicMock, mock_content: MagicMock,
    ) -> None:
        """Returns warnings when configs are outdated."""
        mock_docker.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=""),
            subprocess.CompletedProcess([], 0, stdout="netdata\n"),
        ]
        warnings = check_netdata_config()
        assert len(warnings) == 2
        assert all("outdated" in w for w in warnings)

    @patch("truefan.commands.netdata._docker")
    def test_multiple_containers_skips(self, mock_docker: MagicMock) -> None:
        """Returns empty list when multiple Netdata containers are found."""
        mock_docker.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=""),
            subprocess.CompletedProcess([], 0, stdout="netdata-1\nnetdata-2\n"),
        ]
        assert check_netdata_config() == []
