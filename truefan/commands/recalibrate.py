"""The recalibrate subcommand: re-run fan calibration on existing config."""

import sys
import time
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.calibrate import calibrate_fans
from truefan.config import Config, FanConfig, load_config, save_config
from truefan.fans import detect_fans, reset_thresholds
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
    config = load_config(config_path)

    print("Detecting fans...")
    fan_zones = detect_fans(conn)
    if not fan_zones:
        print("No fans detected.", file=sys.stderr)
        sys.exit(1)
    for name, zone in sorted(fan_zones.items()):
        print(f"  {name} -> {zone}")

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
        curves=config.curves,
        fans=MappingProxyType(fans),
    )
    save_config(config_path, updated)
    print(f"Config updated: {config_path}")
