"""Tests for truefan.watchdog."""

import os
import signal
import time

from tests.mocks import FanSimulator
from truefan.watchdog import start


def _make_sim() -> FanSimulator:
    """Create a simple FanSimulator."""
    sim = FanSimulator(fans={
        "CPU_FAN1": {"max_rpm": 1500, "stall_below": 0},
        "SYS_FAN1": {"max_rpm": 1200, "stall_below": 0},
    })
    sim.set_fan_zone("CPU_FAN1", "cpu")
    sim.set_fan_zone("SYS_FAN1", "peripheral")
    return sim


# ---------------------------------------------------------------------------
# #### start
# ---------------------------------------------------------------------------

class TestWatchdogStart:
    """Tests for watchdog.start with real processes."""

    def test_child_clean_exit(self) -> None:
        """Watchdog exits when child exits cleanly (exit code 0)."""
        import sys
        sim = _make_sim()
        start(lambda: sys.exit(0), sim, restart_delay=0.1)

    def test_child_crash_restarts(self) -> None:
        """Watchdog restarts the child after a crash, then exits on clean run."""
        # Use a file to coordinate state across fork boundaries.
        import tempfile
        marker = os.path.join(tempfile.mkdtemp(), "runs")

        def _daemon() -> None:
            if not os.path.exists(marker):
                # First run: create marker and crash.
                with open(marker, "w") as f:
                    f.write("1")
                raise RuntimeError("simulated crash")
            else:
                # Second run: exit cleanly.
                import sys
                sys.exit(0)

        sim = _make_sim()
        start(_daemon, sim, restart_delay=0.1)

        # Verify the marker exists (first run happened and crashed).
        assert os.path.exists(marker)

        # Verify full speed was set after crash (raw command in parent's sim).
        full_speed_cmds = [
            c for c in sim.raw_commands
            if c == (0x30, 0x45, bytes([0x01, 0x01]))
        ]
        assert len(full_speed_cmds) >= 1

    def test_sigterm_forwarded_to_child(self) -> None:
        """SIGTERM to the watchdog is forwarded to the child."""
        import tempfile
        marker = os.path.join(tempfile.mkdtemp(), "got_sigterm")

        def _daemon() -> None:
            # Set up SIGTERM handler that creates a marker file.
            def _handler(signum: int, frame: object) -> None:
                with open(marker, "w") as f:
                    f.write("1")
                import sys
                sys.exit(0)

            signal.signal(signal.SIGTERM, _handler)
            # Block until signal arrives.
            while True:
                time.sleep(0.1)

        sim = _make_sim()
        watchdog_pid = os.fork()
        if watchdog_pid == 0:
            # Child becomes the watchdog.
            try:
                start(_daemon, sim, restart_delay=0.1)
            except SystemExit:
                pass
            os._exit(0)

        # Parent: give the watchdog time to start its child, then send SIGTERM.
        time.sleep(0.5)
        os.kill(watchdog_pid, signal.SIGTERM)
        os.waitpid(watchdog_pid, 0)

        assert os.path.exists(marker), "Child did not receive SIGTERM"

    def test_sighup_forwarded_to_child(self) -> None:
        """SIGHUP to the watchdog is forwarded to the child."""
        import tempfile
        marker = os.path.join(tempfile.mkdtemp(), "got_sighup")

        def _daemon() -> None:
            def _hup_handler(signum: int, frame: object) -> None:
                with open(marker, "w") as f:
                    f.write("1")

            def _term_handler(signum: int, frame: object) -> None:
                import sys
                sys.exit(0)

            signal.signal(signal.SIGHUP, _hup_handler)
            signal.signal(signal.SIGTERM, _term_handler)
            while True:
                time.sleep(0.1)

        sim = _make_sim()
        watchdog_pid = os.fork()
        if watchdog_pid == 0:
            try:
                start(_daemon, sim, restart_delay=0.1)
            except SystemExit:
                pass
            os._exit(0)

        # Send SIGHUP, then SIGTERM to clean up.
        time.sleep(0.5)
        os.kill(watchdog_pid, signal.SIGHUP)
        time.sleep(0.3)
        os.kill(watchdog_pid, signal.SIGTERM)
        os.waitpid(watchdog_pid, 0)

        assert os.path.exists(marker), "Child did not receive SIGHUP"

    def test_nonzero_exit_restarts(self) -> None:
        """sys.exit(1) in child triggers restart, not clean exit."""
        import sys
        import tempfile
        counter = os.path.join(tempfile.mkdtemp(), "runs")

        def _daemon() -> None:
            if not os.path.exists(counter):
                with open(counter, "w") as f:
                    f.write("1")
                sys.exit(1)  # non-zero — should restart
            else:
                sys.exit(0)  # clean exit — should stop

        sim = _make_sim()
        start(_daemon, sim, restart_delay=0.1)
        assert os.path.exists(counter)

    def test_abrupt_os_exit_restarts(self) -> None:
        """os._exit() in child triggers restart."""
        import tempfile
        counter = os.path.join(tempfile.mkdtemp(), "runs")

        def _daemon() -> None:
            if not os.path.exists(counter):
                with open(counter, "w") as f:
                    f.write("1")
                os._exit(42)  # abrupt exit
            else:
                import sys
                sys.exit(0)

        sim = _make_sim()
        start(_daemon, sim, restart_delay=0.1)
        assert os.path.exists(counter)

    def test_child_killed_by_signal_restarts(self) -> None:
        """Child killed by SIGKILL triggers restart."""
        import tempfile
        counter_path = os.path.join(tempfile.mkdtemp(), "runs")

        def _daemon() -> None:
            if not os.path.exists(counter_path):
                with open(counter_path, "w") as f:
                    f.write("1")
                os.kill(os.getpid(), signal.SIGKILL)  # kill self
            else:
                import sys
                sys.exit(0)

        sim = _make_sim()
        start(_daemon, sim, restart_delay=0.1)
        assert os.path.exists(counter_path)

    def test_multiple_crashes_keeps_restarting(self) -> None:
        """Watchdog keeps restarting through multiple crashes."""
        import tempfile
        counter_path = os.path.join(tempfile.mkdtemp(), "count")

        def _daemon() -> None:
            count = 0
            if os.path.exists(counter_path):
                count = int(open(counter_path).read())
            count += 1
            with open(counter_path, "w") as f:
                f.write(str(count))
            if count < 3:
                raise RuntimeError(f"crash #{count}")
            import sys
            sys.exit(0)

        sim = _make_sim()
        start(_daemon, sim, restart_delay=0.1)

        assert int(open(counter_path).read()) == 3

        # Full speed should have been set after each crash (2 crashes).
        full_speed_cmds = [
            c for c in sim.raw_commands
            if c == (0x30, 0x45, bytes([0x01, 0x01]))
        ]
        assert len(full_speed_cmds) >= 2

    def test_sigusr1_forwarded_to_child(self) -> None:
        """SIGUSR1 to the watchdog is forwarded to the child."""
        import tempfile
        marker = os.path.join(tempfile.mkdtemp(), "got_sigusr1")

        def _daemon() -> None:
            def _usr1_handler(signum: int, frame: object) -> None:
                with open(marker, "w") as f:
                    f.write("1")

            def _term_handler(signum: int, frame: object) -> None:
                import sys
                sys.exit(0)

            signal.signal(signal.SIGUSR1, _usr1_handler)
            signal.signal(signal.SIGTERM, _term_handler)
            while True:
                time.sleep(0.1)

        sim = _make_sim()
        watchdog_pid = os.fork()
        if watchdog_pid == 0:
            try:
                start(_daemon, sim, restart_delay=0.1)
            except SystemExit:
                pass
            os._exit(0)

        # Send SIGUSR1, then SIGTERM to clean up.
        time.sleep(0.5)
        os.kill(watchdog_pid, signal.SIGUSR1)
        time.sleep(0.3)
        os.kill(watchdog_pid, signal.SIGTERM)
        os.waitpid(watchdog_pid, 0)

        assert os.path.exists(marker), "Child did not receive SIGUSR1"

    def test_child_closes_pidfile_fd(self) -> None:
        """After fork, only the watchdog holds the PID file lock.

        If the watchdog exits, the lock is released — the child's
        closed fd doesn't keep it alive.
        """
        import tempfile
        from pathlib import Path
        from truefan.pidfile import PidFile, is_locked

        pid_path = Path(os.path.join(tempfile.mkdtemp(), "test.pid"))
        result_path = os.path.join(tempfile.mkdtemp(), "lock_after_parent_death")

        def _daemon() -> None:
            """Wait for parent to die, then check if lock is released."""
            # Ignore SIGTERM so PR_SET_PDEATHSIG doesn't kill us before we check.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            # Wait until reparented to init (parent died).
            for _ in range(50):
                if os.getppid() == 1:
                    break
                time.sleep(0.1)
            held = is_locked(pid_path)
            with open(result_path, "w") as f:
                f.write("held" if held else "released")
            os._exit(0)

        sim = _make_sim()
        # Fork so we can kill the watchdog from the test process.
        watchdog_pid = os.fork()
        if watchdog_pid == 0:
            try:
                with PidFile(pid_path) as pf:
                    start(_daemon, sim, restart_delay=0.1, close_fds=[pf.fileno()])
            except SystemExit:
                pass
            os._exit(0)

        # Give the watchdog time to fork its child, then kill the watchdog.
        time.sleep(0.5)
        os.kill(watchdog_pid, signal.SIGKILL)
        os.waitpid(watchdog_pid, 0)

        # Wait for child to check the lock and write result.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if os.path.exists(result_path):
                break
            time.sleep(0.1)

        assert os.path.exists(result_path), "Child never wrote result"
        result = open(result_path).read()
        assert result == "released", (
            "Lock should be released after watchdog death, but child saw: " + result
        )

    def test_watchdog_death_terminates_child(self) -> None:
        """If the watchdog dies, the child receives SIGTERM via PR_SET_PDEATHSIG."""
        import tempfile
        marker = os.path.join(tempfile.mkdtemp(), "child_exit")

        def _daemon() -> None:
            def _term_handler(signum: int, frame: object) -> None:
                with open(marker, "w") as f:
                    f.write("sigterm")
                os._exit(0)

            signal.signal(signal.SIGTERM, _term_handler)
            while True:
                time.sleep(0.1)

        sim = _make_sim()
        watchdog_pid = os.fork()
        if watchdog_pid == 0:
            try:
                start(_daemon, sim, restart_delay=0.1)
            except SystemExit:
                pass
            os._exit(0)

        # Give the watchdog time to fork its child, then kill it abruptly.
        time.sleep(0.5)
        os.kill(watchdog_pid, signal.SIGKILL)
        os.waitpid(watchdog_pid, 0)

        # Give the child time to receive SIGTERM from PR_SET_PDEATHSIG and write marker.
        time.sleep(1.0)

        assert os.path.exists(marker), "Child did not exit after watchdog death"
        assert open(marker).read() == "sigterm"


class TestPrSetPdeathsig:
    """Verify that PR_SET_PDEATHSIG actually delivers the signal."""

    def test_child_receives_signal_on_parent_death(self) -> None:
        """When a parent dies, child with PR_SET_PDEATHSIG gets the signal.

        Uses real processes to validate kernel behavior, not mocked.
        """
        import ctypes
        import tempfile

        marker = os.path.join(tempfile.mkdtemp(), "got_signal")

        # Fork a parent that will fork a child with PR_SET_PDEATHSIG.
        parent_pid = os.fork()
        if parent_pid == 0:
            # Intermediate parent — fork the child, then die.
            child_pid = os.fork()
            if child_pid == 0:
                # Child — set PR_SET_PDEATHSIG and wait.
                PR_SET_PDEATHSIG = 1
                libc = ctypes.CDLL("libc.so.6", use_errno=True)
                libc.prctl(PR_SET_PDEATHSIG, signal.SIGUSR2)

                def _handler(signum: int, frame: object) -> None:
                    fd = os.open(marker, os.O_CREAT | os.O_WRONLY, 0o644)
                    os.write(fd, str(signum).encode())
                    os.close(fd)
                    os._exit(0)

                signal.signal(signal.SIGUSR2, _handler)

                # Check if parent already died (race condition guard).
                if os.getppid() == 1:
                    fd = os.open(marker, os.O_CREAT | os.O_WRONLY, 0o644)
                    os.write(fd, b"orphaned_before_signal")
                    os.close(fd)
                    os._exit(0)

                # Wait for signal.
                for _ in range(50):
                    time.sleep(0.1)
                # Timed out — no signal received.
                fd = os.open(marker, os.O_CREAT | os.O_WRONLY, 0o644)
                os.write(fd, b"timeout")
                os.close(fd)
                os._exit(1)

            # Intermediate parent: give child time to set up, then die.
            time.sleep(0.3)
            os._exit(0)

        # Original process: wait for intermediate parent to die.
        os.waitpid(parent_pid, 0)

        # Wait for the child to write the marker.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if os.path.exists(marker):
                break
            time.sleep(0.1)

        assert os.path.exists(marker), "Child never wrote marker file"
        content = open(marker).read()
        assert content == str(signal.SIGUSR2), f"Expected SIGUSR2 ({signal.SIGUSR2}), got: {content}"
