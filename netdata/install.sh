#!/usr/bin/env bash
# Install TrueFan Netdata configs into a Docker-based Netdata instance.
#
# Usage:
#   sudo ./install.sh [--container NAME] [--force] child|parent|standalone
#
# Targets:
#   child       statsd app config  (-> /etc/netdata/statsd.d/)
#   parent      alert definitions  (-> /etc/netdata/health.d/)
#   standalone  both (single-box setup, no streaming)
#
# If --container is omitted, the script auto-detects by looking for
# a single running container whose name contains "netdata".
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# -- Helpers ------------------------------------------------------------------

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
warn() { printf 'WARNING: %s\n' "$1" >&2; }

# Check whether a path inside a container lives on a host mount (bind or volume).
is_persistent() {
    local container="$1" path="$2"
    local mounts
    mounts="$(docker inspect "$container" \
        --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}')"
    while IFS= read -r mountpoint; do
        [ -z "$mountpoint" ] && continue
        case "$path" in "$mountpoint"|"$mountpoint"/*) return 0 ;; esac
    done <<< "$mounts"
    return 1
}

warn_if_ephemeral() {
    local container="$1" path="$2"
    if ! is_persistent "$container" "$path"; then
        warn "$path is not on a host mount -- it will be lost when the container is recreated."
        warn "Consider adding a bind mount for $(dirname "$path")/ in your compose file."
    fi
}

usage() {
    printf 'Usage: %s [--container NAME] [--force] child|parent|standalone\n' "$(basename "$0")" >&2
    exit 1
}

# -- Parse args ---------------------------------------------------------------

CONTAINER=""
TARGET=""
FORCE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --container)
            [ $# -ge 2 ] || usage
            CONTAINER="$2"
            shift 2
            ;;
        --force|-f)
            FORCE=1
            shift
            ;;
        child|parent|standalone)
            [ -z "$TARGET" ] || fail "Target already set to '$TARGET'."
            TARGET="$1"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

[ -n "$TARGET" ] || usage

# -- Checks -------------------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
    fail "'docker' not found in PATH."
fi

if ! docker info >/dev/null 2>&1; then
    fail "Cannot connect to Docker. Try running with sudo."
fi

# -- Container detection ------------------------------------------------------

detect_container() {
    local matches
    matches="$(docker ps --filter status=running --format '{{.Names}}' | grep -i netdata || true)"

    if [ -z "$matches" ]; then
        fail "No running container with 'netdata' in its name. Use --container NAME."
    fi

    local count
    count="$(printf '%s\n' "$matches" | wc -l)"

    if [ "$count" -gt 1 ]; then
        printf 'ERROR: Multiple Netdata containers found:\n' >&2
        printf '  %s\n' $matches >&2
        printf 'Use --container NAME to pick one.\n' >&2
        exit 1
    fi

    printf '%s' "$matches"
}

if [ -z "$CONTAINER" ]; then
    CONTAINER="$(detect_container)"
    echo "Detected container: $CONTAINER"
fi

# Verify the container is running.
if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    fail "Container '$CONTAINER' not found."
fi

STATE="$(docker inspect -f '{{.State.Status}}' "$CONTAINER")"
if [ "$STATE" != "running" ]; then
    fail "Container '$CONTAINER' exists but is $STATE, not running."
fi

# -- Install functions --------------------------------------------------------

install_child() {
    local src="$SCRIPT_DIR/child/truefan.conf"
    local dest="/etc/netdata/statsd.d/truefan.conf"

    [ -f "$src" ] || fail "Source config not found: $src"

    if ! docker exec "$CONTAINER" test -d /etc/netdata/statsd.d 2>/dev/null; then
        warn "Directory /etc/netdata/statsd.d/ does not exist in the container -- creating it."
        docker exec "$CONTAINER" mkdir -p /etc/netdata/statsd.d
    fi

    if [ "$FORCE" -eq 0 ] && docker exec "$CONTAINER" test -f "$dest" 2>/dev/null; then
        existing="$(docker exec "$CONTAINER" cat "$dest")"
        new="$(cat "$src")"
        if [ "$existing" = "$new" ]; then
            echo "statsd config is already up to date."
            return 1  # signal: no changes
        fi
        echo "statsd config differs -- updating."
    fi

    warn_if_ephemeral "$CONTAINER" "$dest"
    docker cp "$src" "$CONTAINER:$dest"
    echo "Installed $src -> $CONTAINER:$dest"
}

install_parent() {
    local src="$SCRIPT_DIR/parent/truefan_alerts.conf"
    local dest="/etc/netdata/health.d/truefan_alerts.conf"

    [ -f "$src" ] || fail "Source config not found: $src"

    if ! docker exec "$CONTAINER" test -d /etc/netdata/health.d 2>/dev/null; then
        warn "Directory /etc/netdata/health.d/ does not exist in the container -- creating it."
        docker exec "$CONTAINER" mkdir -p /etc/netdata/health.d
    fi

    if [ "$FORCE" -eq 0 ] && docker exec "$CONTAINER" test -f "$dest" 2>/dev/null; then
        existing="$(docker exec "$CONTAINER" cat "$dest")"
        new="$(cat "$src")"
        if [ "$existing" = "$new" ]; then
            echo "Alert config is already up to date."
            return 1  # signal: no changes
        fi
        echo "Alert config differs -- updating."
    fi

    warn_if_ephemeral "$CONTAINER" "$dest"
    docker cp "$src" "$CONTAINER:$dest"
    echo "Installed $src -> $CONTAINER:$dest"
}

# -- Run ----------------------------------------------------------------------

changed=0

case "$TARGET" in
    child)
        install_child && changed=1 || true
        ;;
    parent)
        install_parent && changed=1 || true
        ;;
    standalone)
        install_child && changed=1 || true
        install_parent && changed=1 || true
        ;;
esac

if [ "$changed" -eq 0 ]; then
    echo "Everything is already up to date. Nothing to do."
    exit 0
fi

# -- Restart ------------------------------------------------------------------

echo "Restarting $CONTAINER..."
docker restart "$CONTAINER" >/dev/null
echo "Waiting for Netdata to come back..."

# Wait for the container process to be running.
for _ in 1 2 3 4 5; do
    sleep 2
    STATE="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
    if [ "$STATE" = "running" ]; then
        echo "Netdata is running."
        break
    fi
done
if [ "$STATE" != "running" ]; then
    fail "Container did not come back after restart. Check 'docker logs $CONTAINER'."
fi

# Wait for statsd to bind (only relevant for child/standalone).
if [ "$TARGET" != "parent" ]; then
    for _ in 1 2 3 4 5 6; do
        if docker exec "$CONTAINER" grep -q ':1FBD ' /proc/net/udp /proc/net/udp6 2>/dev/null; then
            echo "statsd UDP port 8125 is listening."
            exit 0
        fi
        sleep 2
    done
    warn "statsd UDP port 8125 is not listening after 12s. Check the Netdata statsd config."
fi
