"""Tests for truefan.metrics."""

import socket

from truefan.metrics import send_daemon_restart, send_target_rpm, send_zone_duty


def _receive_one(sock: socket.socket) -> str:
    """Read a single UDP datagram with a short timeout."""
    sock.settimeout(1.0)
    data, _ = sock.recvfrom(1024)
    return data.decode()


# ---------------------------------------------------------------------------
# #### send_target_rpm
# ---------------------------------------------------------------------------

class TestSendTargetRpm:
    """Tests for send_target_rpm."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted statsd gauge line."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_target_rpm("FAN1", 620, port=port)
            assert _receive_one(sock) == "truefan.fan.FAN1.target_rpm:620|g"

    def test_socket_error_does_not_raise(self) -> None:
        """UDP failure is swallowed, not raised."""
        send_target_rpm("FAN1", 620, port=1)


# ---------------------------------------------------------------------------
# #### send_zone_duty
# ---------------------------------------------------------------------------

class TestSendZoneDuty:
    """Tests for send_zone_duty."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted zone duty gauge."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_zone_duty("cpu", 75, port=port)
            assert _receive_one(sock) == "truefan.zone.cpu.duty:75|g"


# ---------------------------------------------------------------------------
# #### send_daemon_restart
# ---------------------------------------------------------------------------

class TestSendDaemonRestart:
    """Tests for send_daemon_restart."""

    def test_sends_correct_statsd_counter(self) -> None:
        """Sends a correctly formatted restart counter increment."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_daemon_restart(port=port)
            assert _receive_one(sock) == "truefan.daemon.restarts:1|c"
