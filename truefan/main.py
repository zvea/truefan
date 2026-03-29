"""CLI entry point and argument parsing."""

import argparse
import sys
from pathlib import Path

from importlib.metadata import version

from truefan.config import DEFAULT_CONFIG_FILENAME


def _default_config_path() -> Path:
    """Config file next to the script itself."""
    return Path(__file__).parent.parent / DEFAULT_CONFIG_FILENAME


_CONFIG_HELP: str = (
    f"Path to config file (default: {DEFAULT_CONFIG_FILENAME} next to the script)"
)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to a subcommand.

    --config can appear before or after the subcommand name.
    """
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument("--config", type=Path, default=None, help=_CONFIG_HELP)

    parser = argparse.ArgumentParser(
        prog="truefan",
        description="Fan control daemon for TrueNAS SCALE.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('truefan')}",
    )
    parser.add_argument("--config", type=Path, default=None, help=_CONFIG_HELP)

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Detect fans, calibrate, and generate a config file",
                    parents=[config_parent])
    sub.add_parser("run", help="Start the fan control daemon",
                    parents=[config_parent])
    sub.add_parser("recalibrate", help="Re-run fan calibration on an existing config",
                    parents=[config_parent])
    sub.add_parser("sensors", help="Show all detected temperature and fan sensors")
    sub.add_parser("reload", help="Send SIGHUP to the running daemon to reload config",
                    parents=[config_parent])
    check_parser = sub.add_parser("check", help="Validate the config file",
                                  parents=[config_parent])
    check_parser.add_argument(
        "--syntax-only", action="store_true",
        help="Check only TOML syntax and structure, skip hardware checks",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    # Resolve --config: use the value from whichever position it was given,
    # falling back to the default.
    if args.config is None:
        args.config = _default_config_path()

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
    elif args.command == "check":
        from truefan.commands.check import run_check
        run_check(args.config, syntax_only=args.syntax_only)


if __name__ == "__main__":
    main()
