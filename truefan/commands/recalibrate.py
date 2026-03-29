"""The recalibrate subcommand: re-run fan calibration on existing config."""

import sys
import time
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.calibrate import calibrate_fans
from truefan.commands import load_and_validate
from truefan.config import DEFAULT_CURVES, Config, Curve, FanConfig, save_config
from truefan.fans import detect_fans, reset_thresholds
from truefan.sensors import SensorClass, available_backends
from truefan.pidfile import PidFile, PidFileError


def run_recalibrate(
    config_path: Path,
    conn: BmcConnection | None = None,
    sleep: Callable[[float], None] = time.sleep,
    pid_path: Path | None = None,
) -> None:
    """Re-run fan calibration and update setpoints in existing config."""
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if conn is None:
        conn = IpmitoolConnection()

    if pid_path is not None:
        try:
            with PidFile(pid_path):
                _do_recalibrate(conn, config_path, sleep)
        except PidFileError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        _do_recalibrate(conn, config_path, sleep)


def _do_recalibrate(
    conn: BmcConnection,
    config_path: Path,
    sleep: Callable[[float], None],
) -> None:
    """Core recalibration logic, called while holding the PID lock."""
    config = load_and_validate(config_path, conn)

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
    # Merge: keep user curve overrides, add defaults for newly detected
    # classes, remove curves for classes no longer present.
    curves: dict[SensorClass, Curve] = {}
    for cls in detected_classes:
        if cls in config.curves:
            curves[cls] = config.curves[cls]
        elif cls in DEFAULT_CURVES:
            curves[cls] = DEFAULT_CURVES[cls]
    for cls in sorted(detected_classes, key=lambda c: c.value):
        print(f"  {cls.value}")

    print("Resetting BMC thresholds...")
    reset_thresholds(conn)

    print("Running calibration (this takes a few minutes)...")
    results = calibrate_fans(conn, fan_zones, sleep=sleep)

    fans: dict[str, FanConfig] = {}
    for r in results:
        fans[r.fan_name] = FanConfig(zone=r.zone, setpoints=r.setpoints)
        duties = sorted(r.setpoints.keys())
        print(f"  {r.fan_name}: {len(duties)} setpoints, min duty {duties[0]}%")

    updated = Config(
        poll_interval_seconds=config.poll_interval_seconds,
        curves=MappingProxyType(curves),
        fans=MappingProxyType(fans),
    )
    save_config(config_path, updated)
    print(f"Config updated: {config_path}")
