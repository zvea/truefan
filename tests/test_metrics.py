"""Tests for truefan.metrics."""

import socket

from truefan.metrics import (
    send_actual_rpm,
    send_daemon_restart,
    send_min_setpoint_rpm,
    send_stalls,
    send_target_rpm,
    send_temperature,
    send_thermal_load,
    send_uptime,
    send_zone_duty,
)


def _receive_one(sock: socket.socket) -> str:
    """Read a single UDP datagram with a short timeout."""
    sock.settimeout(1.0)
    data, _ = sock.recvfrom(1024)
    return data.decode()


# ---------------------------------------------------------------------------
# #### send_actual_rpm
# ---------------------------------------------------------------------------

class TestSendActualRpm:
    """Tests for send_actual_rpm."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted statsd gauge line."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_actual_rpm("FAN1", 620, port=port)
            assert _receive_one(sock) == "truefan.fan.FAN1.actual_rpm:620|g"

    def test_socket_error_does_not_raise(self) -> None:
        """UDP failure is swallowed, not raised."""
        send_actual_rpm("FAN1", 620, port=1)


# ---------------------------------------------------------------------------
# #### send_min_setpoint_rpm
# ---------------------------------------------------------------------------

class TestSendMinSetpointRpm:
    """Tests for send_min_setpoint_rpm."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted statsd gauge line."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_min_setpoint_rpm("FAN1", 320, port=port)
            assert _receive_one(sock) == "truefan.fan.FAN1.min_setpoint_rpm:320|g"

    def test_socket_error_does_not_raise(self) -> None:
        """UDP failure is swallowed, not raised."""
        send_min_setpoint_rpm("FAN1", 320, port=1)


# ---------------------------------------------------------------------------
# #### send_stalls
# ---------------------------------------------------------------------------

class TestSendStalls:
    """Tests for send_stalls."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted stall count gauge."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_stalls("FAN1", 1, port=port)
            assert _receive_one(sock) == "truefan.fan.FAN1.stalls:1|g"

    def test_sends_zero_when_no_stall(self) -> None:
        """Sends 0 when no stall occurred this cycle."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_stalls("FAN1", 0, port=port)
            assert _receive_one(sock) == "truefan.fan.FAN1.stalls:0|g"

    def test_socket_error_does_not_raise(self) -> None:
        """UDP failure is swallowed, not raised."""
        send_stalls("FAN1", 1, port=1)


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
# #### send_thermal_load
# ---------------------------------------------------------------------------

class TestSendThermalLoad:
    """Tests for send_thermal_load."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted thermal load gauge."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_thermal_load("ipmi_CPU_Temp", 45.0, port=port)
            assert _receive_one(sock) == "truefan.sensor.ipmi_CPU_Temp.thermal_load:45|g"


# ---------------------------------------------------------------------------
# #### send_temperature
# ---------------------------------------------------------------------------

class TestSendTemperature:
    """Tests for send_temperature."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted temperature gauge in °C."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_temperature("ipmi_CPU_Temp", 42.5, port=port)
            assert _receive_one(sock) == "truefan.sensor.ipmi_CPU_Temp.temperature:42|g"

    def test_no_listener_does_not_raise(self) -> None:
        """send_temperature does not raise when nothing listens."""
        send_temperature("ipmi_CPU_Temp", 42.5, port=1)


# ---------------------------------------------------------------------------
# #### send_uptime
# ---------------------------------------------------------------------------

class TestSendUptime:
    """Tests for send_uptime."""

    def test_sends_correct_statsd_gauge(self) -> None:
        """Sends a correctly formatted uptime gauge in seconds."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            send_uptime(3600, port=port)
            assert _receive_one(sock) == "truefan.daemon.uptime:3600|g"


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


# ---------------------------------------------------------------------------
# #### No Netdata running
# ---------------------------------------------------------------------------

class TestNoNetdata:
    """All metric functions work silently when no listener is present."""

    def test_actual_rpm_no_listener(self) -> None:
        """send_actual_rpm does not raise when nothing listens."""
        send_actual_rpm("FAN1", 620, port=1)

    def test_min_setpoint_rpm_no_listener(self) -> None:
        """send_min_setpoint_rpm does not raise when nothing listens."""
        send_min_setpoint_rpm("FAN1", 320, port=1)

    def test_target_rpm_no_listener(self) -> None:
        """send_target_rpm does not raise when nothing listens."""
        send_target_rpm("FAN1", 620, port=1)

    def test_stalls_no_listener(self) -> None:
        """send_stalls does not raise when nothing listens."""
        send_stalls("FAN1", 1, port=1)

    def test_zone_duty_no_listener(self) -> None:
        """send_zone_duty does not raise when nothing listens."""
        send_zone_duty("cpu", 50, port=1)

    def test_daemon_restart_no_listener(self) -> None:
        """send_daemon_restart does not raise when nothing listens."""
        send_daemon_restart(port=1)

    def test_thermal_load_no_listener(self) -> None:
        """send_thermal_load does not raise when nothing listens."""
        send_thermal_load("ipmi_CPU_Temp", 45.0, port=1)

    def test_uptime_no_listener(self) -> None:
        """send_uptime does not raise when nothing listens."""
        send_uptime(100, port=1)

    def test_unreachable_host(self) -> None:
        """Metrics to an unreachable host do not raise."""
        send_actual_rpm("FAN1", 620, host="192.0.2.1", port=8125)
        send_min_setpoint_rpm("FAN1", 320, host="192.0.2.1", port=8125)
        send_stalls("FAN1", 0, host="192.0.2.1", port=8125)
        send_target_rpm("FAN1", 620, host="192.0.2.1", port=8125)
        send_zone_duty("cpu", 50, host="192.0.2.1", port=8125)
        send_daemon_restart(host="192.0.2.1", port=8125)
        send_uptime(100, host="192.0.2.1", port=8125)
