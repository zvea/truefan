"""The netdata subcommand: install, uninstall, and check Netdata configs."""

import logging
import subprocess
import sys
import time
from importlib.resources import files
from typing import Final

_log: Final = logging.getLogger(__name__)

# Config files shipped with the package and their container destinations.
_CONFIGS: Final = (
    ("statsd.d/truefan.conf", "/etc/netdata/statsd.d/truefan.conf"),
    ("health.d/truefan_alerts.conf", "/etc/netdata/health.d/truefan_alerts.conf"),
)

_STATSD_PORT_HEX: Final = "1FBD"  # 8125 in hex


def _packaged_content(relative_path: str) -> str:
    """Read a config file from the installed package."""
    return files("truefan.netdata_configs").joinpath(relative_path).read_text()


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a docker command, returning the completed process.

    Raises RuntimeError with a clear message on failure.
    """
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise RuntimeError("'docker' not found in PATH")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        raise RuntimeError(f"docker {args[0]} failed: {stderr}") from e


def _docker_ok(*args: str) -> subprocess.CompletedProcess[str] | None:
    """Run a docker command, returning None on failure instead of raising."""
    try:
        return _docker(*args)
    except RuntimeError:
        return None


def detect_container(container: str | None) -> str:
    """Detect or validate the Netdata container name.

    If *container* is given, verifies it exists and is running.
    Otherwise, looks for a single running container whose name contains
    "netdata".
    """
    # Verify Docker is reachable.
    try:
        _docker("info")
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if container is not None:
        result = _docker_ok("inspect", "-f", "{{.State.Status}}", container)
        if result is None:
            print(f"Error: container '{container}' not found.", file=sys.stderr)
            sys.exit(1)
        state = result.stdout.strip()
        if state != "running":
            print(
                f"Error: container '{container}' exists but is {state}, not running.",
                file=sys.stderr,
            )
            sys.exit(1)
        return container

    result = _docker(
        "ps", "--filter", "status=running", "--format", "{{.Names}}",
    )
    matches = [n for n in result.stdout.splitlines() if "netdata" in n.lower()]

    if not matches:
        print(
            "Error: no running container with 'netdata' in its name. "
            "Use --container NAME.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(matches) > 1:
        names = ", ".join(matches)
        print(
            f"Error: multiple Netdata containers found: {names}. "
            "Use --container NAME to pick one.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Detected container: {matches[0]}")
    return matches[0]


def _container_file_content(container: str, path: str) -> str | None:
    """Read a file from inside a container, returning None if absent."""
    result = _docker_ok("exec", container, "cat", path)
    if result is None:
        return None
    return result.stdout


def _is_persistent(container: str, path: str) -> bool:
    """Check whether a path inside a container lives on a host mount."""
    result = _docker_ok(
        "inspect", container,
        "--format", '{{range .Mounts}}{{.Destination}}\n{{end}}',
    )
    if result is None:
        return False
    for mountpoint in result.stdout.splitlines():
        mountpoint = mountpoint.strip()
        if not mountpoint:
            continue
        if path == mountpoint or path.startswith(mountpoint + "/"):
            return True
    return False


def _restart_and_wait(container: str, *, wait_for_statsd: bool = True) -> None:
    """Restart the Netdata container and optionally wait for statsd."""
    print(f"Restarting {container}...")
    _docker("restart", container)

    # Wait for the container to be running.
    for attempt in range(5):
        if attempt > 0:
            time.sleep(2)
        result = _docker_ok(
            "inspect", "-f", "{{.State.Status}}", container,
        )
        if result and result.stdout.strip() == "running":
            print("Netdata is running.")
            break
    else:
        print(
            f"Warning: container did not come back after restart. "
            f"Check 'docker logs {container}'.",
            file=sys.stderr,
        )
        return

    if not wait_for_statsd:
        return

    # Wait for statsd UDP port 8125.
    for attempt in range(6):
        if attempt > 0:
            time.sleep(2)
        probe = _docker_ok(
            "exec", container, "grep", "-q", _STATSD_PORT_HEX,
            "/proc/net/udp", "/proc/net/udp6",
        )
        if probe is not None:
            print("statsd UDP port 8125 is listening.")
            return
    print(
        "Warning: statsd UDP port 8125 is not listening after 12s. "
        "Check the Netdata statsd config.",
        file=sys.stderr,
    )


def run_check(container: str | None) -> None:
    """Compare installed configs against packaged versions.

    Prints per-file status and exits 0 if all current, 1 otherwise.
    """
    name = detect_container(container)
    all_ok = True

    for src_path, dest_path in _CONFIGS:
        expected = _packaged_content(src_path)
        actual = _container_file_content(name, dest_path)
        basename = dest_path.rsplit("/", 1)[-1]

        if actual is None:
            print(f"{basename}: missing")
            all_ok = False
        elif actual != expected:
            print(f"{basename}: outdated")
            all_ok = False
        else:
            print(f"{basename}: up to date")

    if not all_ok:
        print("\nRun 'truefan netdata install' to fix.")
        sys.exit(1)


def run_install(container: str | None, force: bool = False) -> None:
    """Copy packaged configs into the Netdata container."""
    name = detect_container(container)
    changed = False

    for src_path, dest_path in _CONFIGS:
        expected = _packaged_content(src_path)
        basename = dest_path.rsplit("/", 1)[-1]
        dest_dir = dest_path.rsplit("/", 1)[0]

        if not force:
            actual = _container_file_content(name, dest_path)
            if actual == expected:
                print(f"{basename} is already up to date.")
                continue
            if actual is not None:
                print(f"{basename} differs -- updating.")

        # Ensure directory exists.
        _docker_ok("exec", name, "mkdir", "-p", dest_dir)

        # Warn on ephemeral storage.
        if not _is_persistent(name, dest_path):
            print(
                f"Warning: {dest_path} is not on a host mount -- "
                "it will be lost when the container is recreated.",
                file=sys.stderr,
            )
            print(
                f"Consider adding a bind mount for {dest_dir}/ "
                "in your compose file.",
                file=sys.stderr,
            )

        # Write file via stdin to avoid temp files.
        try:
            subprocess.run(
                ["docker", "exec", "-i", name, "tee", dest_path],
                input=expected,
                capture_output=True,
                text=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            raise RuntimeError(f"Failed to write {dest_path} to {name}: {e}") from e
        print(f"Installed {basename} -> {name}:{dest_path}")
        changed = True

    if not changed:
        print("Everything is already up to date. Nothing to do.")
        return

    _restart_and_wait(name)


def run_uninstall(container: str | None) -> None:
    """Remove TrueFan's config files from the Netdata container."""
    name = detect_container(container)
    changed = False

    for _, dest_path in _CONFIGS:
        basename = dest_path.rsplit("/", 1)[-1]
        probe = _docker_ok("exec", name, "test", "-f", dest_path)
        if probe is not None:
            _docker("exec", name, "rm", dest_path)
            print(f"Removed {basename} from {name}")
            changed = True

    if not changed:
        print("Nothing to remove.")
        return

    _restart_and_wait(name, wait_for_statsd=False)


def check_netdata_config() -> list[str]:
    """Check Netdata configs and return a list of warnings.

    Returns an empty list if everything is up to date or if Docker is
    unavailable / no container is found (info logged internally for
    those cases).  Returns a list of human-readable warning strings if
    configs are missing or outdated.

    Never raises or exits — designed for the daemon startup path where
    failures are advisory.
    """
    # Check Docker availability.
    try:
        _docker("info")
    except RuntimeError:
        _log.info("Docker not available, skipping Netdata config check")
        return []

    # Auto-detect container.
    try:
        result = _docker(
            "ps", "--filter", "status=running", "--format", "{{.Names}}",
        )
    except RuntimeError:
        _log.info("Could not list Docker containers, skipping Netdata config check")
        return []

    matches = [n for n in result.stdout.splitlines() if "netdata" in n.lower()]
    if not matches:
        _log.info("No Netdata container found, skipping config check")
        return []
    if len(matches) > 1:
        _log.info(
            "Multiple Netdata containers found (%s), skipping config check",
            ", ".join(matches),
        )
        return []

    name = matches[0]
    warnings: list[str] = []

    for src_path, dest_path in _CONFIGS:
        expected = _packaged_content(src_path)
        actual = _container_file_content(name, dest_path)
        basename = dest_path.rsplit("/", 1)[-1]

        if actual is None:
            warnings.append(
                f"Netdata config {basename} is missing from {name} -- "
                "run 'truefan netdata install'"
            )
        elif actual != expected:
            warnings.append(
                f"Netdata config {basename} is outdated in {name} -- "
                "run 'truefan netdata install' to update"
            )

    return warnings
