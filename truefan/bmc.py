"""BMC connection abstraction over IPMI transport.

Provides a testable interface for all IPMI communication. Both fan control
and sensor reading import from here.
"""

import csv
import io
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final

_log: logging.Logger = logging.getLogger(__name__)

_IPMITOOL: Final[str] = "/usr/bin/ipmitool"
_MAX_ATTEMPTS: Final[int] = 3
_RETRY_DELAY_SECONDS: Final[float] = 1.0


@dataclass(frozen=True, kw_only=True)
class TemperatureSensorData:
    """Raw temperature sensor data from the BMC."""

    name: str
    temperature: float | None
    upper_non_critical: float | None = None
    upper_critical: float | None = None


class BmcConnection(ABC):
    """Abstraction over IPMI transport for testability."""

    @abstractmethod
    def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
        """Send a raw IPMI command and return the response data."""

    @abstractmethod
    def set_sensor_thresholds(
        self,
        sensor_name: str,
        lower: tuple[int, int, int],
        upper: tuple[int, int, int],
    ) -> None:
        """Set lower and upper thresholds for a sensor."""

    @abstractmethod
    def list_fans(self) -> list[tuple[str, int | None]]:
        """List all fan sensors. Returns (name, rpm_or_none) pairs."""

    @abstractmethod
    def list_temperature_sensors(self) -> list[TemperatureSensorData]:
        """List all temperature sensors with optional thresholds."""


class BmcError(Exception):
    """Raised when IPMI communication fails."""


class IpmitoolConnection(BmcConnection):
    """BmcConnection backed by ipmitool subprocess calls."""

    def _run(self, args: list[str]) -> str:
        """Run an ipmitool command and return stdout.

        Retries up to three times with a one-second delay between attempts
        to ride out transient BMC errors (e.g. SDR lookup failures).
        """
        cmd = [_IPMITOOL] + args
        cmd_str = " ".join(cmd)
        _log.debug("Running: %s", cmd_str)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                result = subprocess.run(cmd, capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                if attempt < _MAX_ATTEMPTS:
                    stderr = e.stderr.decode().strip() if e.stderr else ""
                    msg = f"{cmd_str} attempt {attempt}/{_MAX_ATTEMPTS} failed"
                    if stderr:
                        msg += f": {stderr}"
                    _log.warning(msg)
                    time.sleep(_RETRY_DELAY_SECONDS)
                    continue
                stderr = e.stderr.decode().strip() if e.stderr else ""
                msg = f"{cmd_str} failed (exit {e.returncode})"
                if stderr:
                    msg += f": {stderr}"
                raise BmcError(msg) from e
            return result.stdout.decode()
        raise AssertionError("unreachable")

    def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
        """Send a raw IPMI command and return the response data."""
        args = ["raw", f"0x{netfn:02x}", f"0x{command:02x}"]
        args.extend(f"0x{b:02x}" for b in data)
        output = self._run(args)
        # Parse hex response bytes if any.
        return bytes(int(b, 16) for b in output.split())

    def set_sensor_thresholds(
        self,
        sensor_name: str,
        lower: tuple[int, int, int],
        upper: tuple[int, int, int],
    ) -> None:
        """Set lower and upper thresholds for a sensor."""
        self._run([
            "sensor", "thresh", sensor_name,
            "lower", str(lower[0]), str(lower[1]), str(lower[2]),
        ])
        self._run([
            "sensor", "thresh", sensor_name,
            "upper", str(upper[0]), str(upper[1]), str(upper[2]),
        ])

    def list_fans(self) -> list[tuple[str, int | None]]:
        """List all fan sensors. Returns (name, rpm_or_none) pairs."""
        output = self._run(["sdr", "type", "fan", "-c"])
        result: list[tuple[str, int | None]] = []
        for row in csv.reader(io.StringIO(output)):
            if len(row) >= 4:
                name, value, _, status = row[0], row[1], row[2], row[3]
                if status == "ok" and value:
                    result.append((name, int(value)))
                else:
                    result.append((name, None))
        return result

    def list_temperature_sensors(self) -> list[TemperatureSensorData]:
        """List all temperature sensors with thresholds from verbose CSV.

        Uses ipmitool sdr type temperature -c -v to get threshold data.
        Columns 9 and 10 (0-indexed) are upper non-critical and upper critical.
        """
        output = self._run(["sdr", "type", "temperature", "-c", "-v"])
        result: list[TemperatureSensorData] = []
        for row in csv.reader(io.StringIO(output)):
            if len(row) < 4:
                continue
            name = row[0]
            status = row[3]
            temp: float | None = None
            unc: float | None = None
            ucr: float | None = None
            if status == "ok" and row[1]:
                temp = float(row[1])
            if len(row) >= 11:
                try:
                    unc = float(row[9])
                except ValueError:
                    pass
                try:
                    ucr = float(row[10])
                except ValueError:
                    pass
            result.append(TemperatureSensorData(
                name=name,
                temperature=temp,
                upper_non_critical=unc,
                upper_critical=ucr,
            ))
        return result
