"""BMC connection abstraction over IPMI transport.

Provides a testable interface for all IPMI communication. Both fan control
and sensor reading import from here.
"""

import csv
import io
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final

_log: logging.Logger = logging.getLogger(__name__)

_IPMITOOL: Final = "/usr/bin/ipmitool"
_MAX_ATTEMPTS: Final = 3
_RETRY_DELAY_SECONDS: Final = 1.0


@dataclass(frozen=True, kw_only=True)
class TemperatureSensorData:
    """Raw temperature sensor data from the BMC."""

    name: str
    temperature: float | None
    upper_non_critical: float | None = None
    upper_critical: float | None = None


@dataclass(frozen=True, kw_only=True)
class SelEntry:
    """A single IPMI System Event Log entry."""

    entry_id: int
    raw_text: str


@dataclass(frozen=True, kw_only=True)
class FanSelEvent:
    """A fan assertion event extracted from a SEL entry."""

    entry_id: int
    fan_name: str
    detail: str


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

    @abstractmethod
    def read_sel(self, last_n: int = 20) -> list[SelEntry]:
        """Read the last N entries from the IPMI System Event Log."""


def parse_fan_sel_events(entries: list[SelEntry]) -> list[FanSelEvent]:
    """Extract fan assertion events from SEL entries.

    Looks for entries containing "Fan" as a sensor type and "Asserted"
    as the event direction.  Keeps parsing minimal — we match on the
    sensor type field containing "Fan " followed by a name, and on
    "Asserted" appearing in the entry (but not "Deasserted").
    """
    events: list[FanSelEvent] = []
    for entry in entries:
        # Format: id | date | time | Fan <NAME> | detail | Asserted | ...
        parts = [p.strip() for p in entry.raw_text.split("|")]
        if len(parts) < 6:
            continue
        sensor_field = parts[3]
        if not sensor_field.startswith("Fan "):
            continue
        direction = parts[5]
        if "Deasserted" in direction:
            continue
        if "Asserted" not in direction:
            continue
        fan_name = sensor_field[4:]  # strip "Fan " prefix
        detail = " | ".join(parts[3:])
        events.append(FanSelEvent(
            entry_id=entry.entry_id,
            fan_name=fan_name,
            detail=detail,
        ))
    return events


_IPMI_DEVICE_PATHS: Final = (
    "/dev/ipmi0",
    "/dev/ipmi/0",
    "/dev/ipmidev/0",
)


def ipmi_device_present() -> bool:
    """Check whether an IPMI device node exists on this machine."""
    return any(os.path.exists(p) for p in _IPMI_DEVICE_PATHS)


def check_ipmi_access() -> str | None:
    """Check IPMI device availability and permissions.

    Returns None if accessible, or an error message explaining the problem.
    """
    device = None
    for p in _IPMI_DEVICE_PATHS:
        if os.path.exists(p):
            device = p
            break
    if device is None:
        return "No IPMI device found (checked /dev/ipmi0, /dev/ipmi/0, /dev/ipmidev/0)"
    if not os.access(device, os.R_OK | os.W_OK):
        return f"Permission denied: {device} (typically requires root)"
    return None


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

    def read_sel(self, last_n: int = 20) -> list[SelEntry]:
        """Read the last N entries from the IPMI System Event Log."""
        output = self._run(["sel", "elist", "last", str(last_n)])
        entries: list[SelEntry] = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # First field is the hex entry ID, separated by |.
            parts = line.split("|", 1)
            if len(parts) < 2:
                continue
            try:
                entry_id = int(parts[0].strip(), 16)
            except ValueError:
                continue
            entries.append(SelEntry(entry_id=entry_id, raw_text=line))
        return entries

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
            name = row[0].strip()
            if not name:
                continue
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
