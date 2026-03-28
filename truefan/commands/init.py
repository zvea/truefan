"""The init subcommand: detect fans, calibrate, generate config."""

import logging
import sys
import time
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.calibrate import calibrate_fans
from truefan.config import (
    DEFAULT_CURVES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    Config,
    Curve,
    FanConfig,
    save_config,
)
from truefan.fans import detect_fans, reset_thresholds
from truefan.sensors import SensorClass, available_backends
from truefan.pidfile import PidFile, PidFileError

_log: logging.Logger = logging.getLogger(__name__)


def _do_init(
    conn: BmcConnection,
    config_path: Path,
    sleep: Callable[[float], None],
) -> None:
    """Core init logic, called while holding the PID lock."""
    print("Detecting fans...")
    fan_zones = detect_fans(conn)
    if not fan_zones:
        print("No fans detected.", file=sys.stderr)
        sys.exit(1)
    for name, zone in sorted(fan_zones.items()):
        print(f"  {name} -> {zone}")

    print("Detecting sensors...")
    backends = available_backends(conn)
    detected_classes: set[SensorClass] = set()
    for backend in backends:
        for reading in backend.scan():
            detected_classes.add(reading.sensor_class)
    curves: dict[SensorClass, Curve] = {
        cls: DEFAULT_CURVES[cls] for cls in detected_classes if cls in DEFAULT_CURVES
    }
    for cls in sorted(detected_classes, key=lambda c: c.value):
        print(f"  {cls.value}")
    if not detected_classes:
        print("  (none)")

    print("Resetting BMC thresholds...")
    reset_thresholds(conn)

    print("Running calibration (this takes a few minutes)...")
    results = calibrate_fans(conn, fan_zones, sleep=sleep)

    fans: dict[str, FanConfig] = {}
    for r in results:
        fans[r.fan_name] = FanConfig(zone=r.zone, setpoints=r.setpoints)
        duties = sorted(r.setpoints.keys())
        print(f"  {r.fan_name}: {len(duties)} setpoints, min duty {duties[0]}%")

    config = Config(
        poll_interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
        curves=MappingProxyType(curves),
        fans=MappingProxyType(fans),
    )
    save_config(config_path, config)
    print(f"Config written to {config_path}")


def run_init(
    config_path: Path,
    conn: BmcConnection | None = None,
    sleep: Callable[[float], None] = time.sleep,
    pid_path: Path | None = None,
) -> None:
    """Detect fans, run calibration, and write a new config file.

    Acquires the PID file lock for the duration to prevent conflicts
    with a running daemon. If conn is None, creates an IpmitoolConnection.
    """
    if config_path.exists():
        print(f"Config already exists: {config_path}", file=sys.stderr)
        sys.exit(1)

    if conn is None:
        conn = IpmitoolConnection()

    if pid_path is not None:
        try:
            with PidFile(pid_path):
                _do_init(conn, config_path, sleep)
        except PidFileError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        _do_init(conn, config_path, sleep)
