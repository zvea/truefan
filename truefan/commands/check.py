"""The check subcommand: validate config without starting the daemon."""

import sys
from pathlib import Path

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.config import ConfigError, load_config, validate_config
from truefan.sensors import available_backends


def run_check(
    config_path: Path,
    syntax_only: bool = False,
    conn: BmcConnection | None = None,
) -> None:
    """Validate the config and print the result.

    With syntax_only, checks only parsing. Otherwise also checks
    against live hardware. Prints errors to stderr and exits 1 on
    failure, prints "Config OK" to stdout on success.
    """
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if not syntax_only:
        if conn is None:
            conn = IpmitoolConnection()

        backends = available_backends(conn)
        readings = []
        for backend in backends:
            readings.extend(backend.scan())

        errors = validate_config(config, conn, readings)
        if errors:
            print("Config validation failed:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            sys.exit(1)

    print("Config OK")
