#!/usr/bin/env bash
# Manage TrueFan Netdata configs in a Docker-based Netdata instance.
#
# Usage:
#   sudo ./setup.sh [--container NAME] [--force] install|uninstall
#
# install    Copy statsd app config and alert definitions into the container.
# uninstall  Remove both configs from the container.
#
# If --container is omitted, the script auto-detects by looking for
# a single running container whose name contains "netdata".
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CONFIGS=(
    "$SCRIPT_DIR/statsd.d/truefan.conf:/etc/netdata/statsd.d/truefan.conf"
    "$SCRIPT_DIR/health.d/truefan_alerts.conf:/etc/netdata/health.d/truefan_alerts.conf"
)

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
    printf 'Usage: %s [--container NAME] [--force] install|uninstall\n' "$(basename "$0")" >&2
    printf '\n' >&2
    printf '  install    Copy statsd app config and alert definitions into the container.\n' >&2
    printf '  uninstall  Remove both configs from the container.\n' >&2
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
        install|uninstall)
            [ -z "$TARGET" ] || fail "Command already set to '$TARGET'."
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

# -- Install / uninstall ------------------------------------------------------

changed=0

if [ "$TARGET" = "install" ]; then
    for entry in "${CONFIGS[@]}"; do
        src="${entry%%:*}"
        dest="${entry##*:}"
        dir="$(dirname "$dest")"

        [ -f "$src" ] || fail "Source config not found: $src"

        if ! docker exec "$CONTAINER" test -d "$dir" 2>/dev/null; then
            warn "Directory $dir/ does not exist in the container -- creating it."
            docker exec "$CONTAINER" mkdir -p "$dir"
        fi

        if [ "$FORCE" -eq 0 ] && docker exec "$CONTAINER" test -f "$dest" 2>/dev/null; then
            existing="$(docker exec "$CONTAINER" cat "$dest")"
            new="$(cat "$src")"
            if [ "$existing" = "$new" ]; then
                echo "$(basename "$dest") is already up to date."
                continue
            fi
            echo "$(basename "$dest") differs -- updating."
        fi

        warn_if_ephemeral "$CONTAINER" "$dest"
        docker cp "$src" "$CONTAINER:$dest"
        echo "Installed $(basename "$src") -> $CONTAINER:$dest"
        changed=1
    done
else
    for entry in "${CONFIGS[@]}"; do
        dest="${entry##*:}"
        if docker exec "$CONTAINER" test -f "$dest" 2>/dev/null; then
            docker exec "$CONTAINER" rm "$dest"
            echo "Removed $dest from $CONTAINER"
            changed=1
        fi
    done
fi

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

# Wait for statsd to bind (only relevant when statsd config is installed).
if [ "$TARGET" = "install" ]; then
    for _ in 1 2 3 4 5 6; do
        if docker exec "$CONTAINER" grep -q ':1FBD ' /proc/net/udp /proc/net/udp6 2>/dev/null; then
            echo "statsd UDP port 8125 is listening."
            exit 0
        fi
        sleep 2
    done
    warn "statsd UDP port 8125 is not listening after 12s. Check the Netdata statsd config."
fi
