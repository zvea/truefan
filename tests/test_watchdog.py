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
