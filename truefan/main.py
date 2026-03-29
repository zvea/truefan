"""CLI entry point and argument parsing."""

import argparse
import sys
from pathlib import Path

from importlib.metadata import version

from truefan.config import DEFAULT_CONFIG_FILENAME


def _default_config_path() -> Path:
    """Config file next to the script itself."""
    return Path(__file__).parent.parent / DEFAULT_CONFIG_FILENAME


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to a subcommand."""
    parser = argparse.ArgumentParser(
        prog="truefan",
        description="Fan control daemon for TrueNAS SCALE.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('truefan')}",
    )
    parser.add_argument(
        "--config", type=Path, default=_default_config_path(),
        help=f"Path to config file (default: {DEFAULT_CONFIG_FILENAME} next to the script)",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Detect fans, calibrate, and generate a config file")
    sub.add_parser("run", help="Start the fan control daemon")
    sub.add_parser("recalibrate", help="Re-run fan calibration on an existing config")
    sub.add_parser("sensors", help="Show all detected temperature and fan sensors")
    sub.add_parser("reload", help="Send SIGHUP to the running daemon to reload config")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    try:
        _dispatch(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _dispatch(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate subcommand."""
    # Local imports: each subcommand imports only what it needs, so e.g.
    # `truefan sensors` doesn't pull in the daemon or calibration code.
    from truefan.pidfile import PID_PATH

    if args.command == "init":
        from truefan.commands.init import run_init
        run_init(args.config, pid_path=PID_PATH)
    elif args.command == "run":
        from truefan.commands.run import run_daemon
        run_daemon(args.config, pid_path=PID_PATH)
    elif args.command == "recalibrate":
        from truefan.commands.recalibrate import run_recalibrate
        run_recalibrate(args.config, pid_path=PID_PATH)
    elif args.command == "sensors":
        from truefan.commands.sensors import run_sensors
        run_sensors()
    elif args.command == "reload":
        from truefan.commands.reload import run_reload
        run_reload(args.config, PID_PATH)


if __name__ == "__main__":
    main()
