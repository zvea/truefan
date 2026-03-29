#!/usr/bin/env bash
# Install the TrueFan statsd app config into the Netdata container.
# Run from the repo root or the netdata/ directory.
set -euo pipefail

CONTAINER="ix-netdata-netdata-1"
DEST="/etc/netdata/statsd.d/truefan.conf"

# Locate the config file relative to this script.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/truefan.conf"

# -- Checks ------------------------------------------------------------------

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
warn() { printf 'WARNING: %s\n' "$1" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    fail "Must run as root (docker commands need it on TrueNAS)."
fi

if ! command -v docker >/dev/null 2>&1; then
    fail "'docker' not found in PATH."
fi

if [ ! -f "$SRC" ]; then
    fail "Source config not found: $SRC"
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    fail "Container '$CONTAINER' not found. Is the Netdata app running?"
fi

STATE="$(docker inspect -f '{{.State.Status}}' "$CONTAINER")"
if [ "$STATE" != "running" ]; then
    fail "Container '$CONTAINER' exists but is $STATE, not running."
fi

# Verify statsd is enabled inside the container.
if docker exec "$CONTAINER" test -d /etc/netdata/statsd.d 2>/dev/null; then
    : # good
else
    warn "Directory /etc/netdata/statsd.d/ does not exist in the container — creating it."
    docker exec "$CONTAINER" mkdir -p /etc/netdata/statsd.d
fi

# -- Install ------------------------------------------------------------------

# Check if already installed and identical.
if docker exec "$CONTAINER" test -f "$DEST" 2>/dev/null; then
    EXISTING="$(docker exec "$CONTAINER" cat "$DEST")"
    NEW="$(cat "$SRC")"
    if [ "$EXISTING" = "$NEW" ]; then
        echo "Config is already installed and up to date. Nothing to do."
        exit 0
    fi
    echo "Config exists but differs — updating."
fi

docker cp "$SRC" "$CONTAINER:$DEST"
echo "Copied $SRC -> $CONTAINER:$DEST"

# -- Restart ------------------------------------------------------------------

echo "Restarting $CONTAINER..."
docker restart "$CONTAINER" >/dev/null
echo "Done. Waiting for Netdata to come back..."

# Give it a moment, then verify it's healthy.
for i in 1 2 3 4 5; do
    sleep 2
    STATE="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
    if [ "$STATE" = "running" ]; then
        echo "Netdata is running."

        # Verify statsd is listening (hex 1FBD = 8125).
        if docker exec "$CONTAINER" grep -q ':1FBD ' /proc/net/udp 2>/dev/null; then
            echo "statsd UDP port 8125 is listening."
        else
            warn "statsd UDP port 8125 is not listening. Check the Netdata statsd config."
        fi
        exit 0
    fi
done

fail "Container did not come back after restart. Check 'docker logs $CONTAINER'."
