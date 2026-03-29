"""CLI subcommand implementations."""

import sys
from pathlib import Path

from truefan.bmc import BmcConnection
from truefan.config import Config, ConfigError, load_config, validate_config
from truefan.sensors import available_backends


def load_and_validate(config_path: Path, conn: BmcConnection) -> Config:
    """Load config, validate against live hardware, exit on error.

    Prints errors to stderr and calls sys.exit(1) if the config is
    broken or doesn't match hardware. Returns the Config on success.
    """
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

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

    return config
