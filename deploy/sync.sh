#!/usr/bin/env bash
# ------------------------------------------------------------------
# Trawlbase — push local changes to the VPS and restart the backend.
#
# Run from your Mac (the project root or anywhere):
#   deploy/sync.sh              # build frontend, rsync, restart service
#   deploy/sync.sh -n           # dry run — show what WOULD transfer, change nothing
#   deploy/sync.sh --no-build   # skip the frontend build (backend-only change)
#   deploy/sync.sh --deps       # also run pip install on the server (deps changed)
#   deploy/sync.sh --no-restart # sync only, don't touch the systemd service
#
# Assumes passwordless SSH is set up (see deploy/DEPLOY.md → "SSH key").
# Override the target without editing this file:
#   REMOTE=stefan@1.2.3.4 REMOTE_DIR=/srv/trawlbase deploy/sync.sh
# ------------------------------------------------------------------
set -euo pipefail

REMOTE="${REMOTE:-stefan@38.49.215.122}"
REMOTE_DIR="${REMOTE_DIR:-/home/stefan/Projects/TrawlBase}"
SERVICE="${SERVICE:-trawlbase}"

# Resolve the project root from this script's location, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DO_BUILD=1
DO_DEPS=0
DO_RESTART=1
DRY_RUN=()

for arg in "$@"; do
    case "$arg" in
        -n|--dry-run) DRY_RUN=(--dry-run) ;;
        --no-build)   DO_BUILD=0 ;;
        --deps)       DO_DEPS=1 ;;
        --no-restart) DO_RESTART=0 ;;
        -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

# 1. Build the frontend locally so the server never needs Node to serve fresh UI.
if [[ "$DO_BUILD" == 1 && "${#DRY_RUN[@]}" == 0 ]]; then
    echo "▶ Building frontend..."
    ( cd "$PROJECT_ROOT/frontend" && npm run build )
fi

# 2. rsync. --delete keeps the server a mirror of local; excluded paths are
#    NEVER deleted (they're server-owned: data, cookies, .env, the DB, venv).
#    Trailing slash on the source = copy CONTENTS of the dir, not the dir itself.
echo "▶ Syncing → $REMOTE:$REMOTE_DIR"
# ${arr[@]+"${arr[@]}"} expands to nothing when empty without tripping `set -u`
# on Bash 3.2 (macOS default), where a bare "${arr[@]}" would error.
rsync -avz --delete ${DRY_RUN[@]+"${DRY_RUN[@]}"} \
    -e ssh \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude 'node_modules/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude '.env' \
    --exclude 'Data-dump/' \
    --exclude 'Phase2-Dump/' \
    --exclude 'Debug-dump/' \
    --exclude 'cookies/' \
    --exclude 'api_key/' \
    --exclude '*.db' \
    --exclude '*.db-wal' \
    --exclude '*.db-shm' \
    --exclude 'Bot/selector_cache.json' \
    "$PROJECT_ROOT/" "$REMOTE:$REMOTE_DIR/"

if [[ "${#DRY_RUN[@]}" != 0 ]]; then
    echo "▶ Dry run complete — nothing changed."
    exit 0
fi

# 3. Optionally refresh Python deps (only when requirements.txt changed).
if [[ "$DO_DEPS" == 1 ]]; then
    echo "▶ Installing Python deps on server..."
    ssh "$REMOTE" "cd $REMOTE_DIR && .venv/bin/pip install -q -r requirements.txt"
fi

# 4. Restart the backend. Needs sudo; see DEPLOY.md for the NOPASSWD sudoers line
#    that makes this non-interactive.
if [[ "$DO_RESTART" == 1 ]]; then
    echo "▶ Restarting $SERVICE..."
    ssh "$REMOTE" "sudo systemctl restart $SERVICE && sudo systemctl --no-pager --lines=0 status $SERVICE" || {
        echo "⚠ Could not restart via sudo. Run manually on the server:"
        echo "    sudo systemctl restart $SERVICE"
    }
fi

echo "✓ Done."
