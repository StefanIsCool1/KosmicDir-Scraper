#!/usr/bin/env bash
# ------------------------------------------------------------------
# Trawlbase — one-command setup for a fresh Ubuntu/Debian mini PC.
#
# Run as root (or with sudo):
#   sudo bash deploy/setup.sh
#
# What it does:
#   1. Installs system packages (Python 3, Node.js, nginx, chromium deps)
#   2. Ensures the deploy user exists (default: stefan — override with DEPLOY_USER=)
#   3. Copies the project into /home/stefan/Projects/TrawlBase (skipped if already run
#      from there, e.g. after deploy/sync.sh)
#   4. Installs Python + Node dependencies
#   5. Installs Playwright's Chromium
#   6. Builds the React frontend
#   7. Configures nginx + systemd + home-dir traversal perms
#   8. Prints next steps (env, DNS + certbot, start)
#
# For the full deploy walkthrough (DNS, SSL, rsync workflow) see deploy/DEPLOY.md.
# ------------------------------------------------------------------
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Safety checks ──────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo bash deploy/setup.sh)"
fi

# Deploy target — must match deploy/nginx.conf and deploy/trawlbase.service.
DEPLOY_USER="${DEPLOY_USER:-stefan}"
PROJECT_DIR="${PROJECT_DIR:-/home/$DEPLOY_USER/Projects/TrawlBase}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log "Starting Trawlbase setup on $(lsb_release -ds 2>/dev/null || cat /etc/os-release | head -1)"

# ── 1. System packages ─────────────────────────────────────────────
log "Updating apt and installing system packages..."

apt-get update -qq

# Chromium deps for Playwright (headless browser)
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    nodejs npm \
    nginx \
    curl unzip git \
    libnss3 libnspr4 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
    libgstreamer-plugins-base1.0-0 || \
    apt-get install -y -qq \
    libnss3 libnspr4 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2  # fallback for older distros

# Certbot for Let's Encrypt SSL (optional but recommended)
apt-get install -y -qq certbot python3-certbot-nginx 2>/dev/null || true

log "System packages installed"

# ── 2. Ensure deploy user exists ───────────────────────────────────
if ! id -u "$DEPLOY_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$DEPLOY_USER"
    log "Created user '$DEPLOY_USER'"
else
    log "User '$DEPLOY_USER' already exists"
fi

# ── 3. Copy project files ──────────────────────────────────────────
# Skip if the script is already running from inside PROJECT_DIR (e.g. you
# rsync'd the repo here first — see deploy/DEPLOY.md), which is the normal path.
if [[ "$REPO_ROOT" != "$PROJECT_DIR" ]]; then
    log "Copying project to $PROJECT_DIR ..."
    mkdir -p "$PROJECT_DIR"
    cp -r "$REPO_ROOT"/* "$PROJECT_DIR/"
    log "Project files in place"
else
    log "Running from $PROJECT_DIR — skipping file copy"
fi
[[ -f "$PROJECT_DIR/.env" ]] || cp "$REPO_ROOT"/.env.example "$PROJECT_DIR"/.env 2>/dev/null || touch "$PROJECT_DIR/.env"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$PROJECT_DIR"

# ── 4. Python dependencies ─────────────────────────────────────────
log "Installing Python dependencies..."
su - "$DEPLOY_USER" -c "cd $PROJECT_DIR && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
log "Python packages installed"

# ── 5. Playwright Chromium ─────────────────────────────────────────
log "Installing Playwright Chromium (this downloads ~150 MB)..."
su - "$DEPLOY_USER" -c "cd $PROJECT_DIR && .venv/bin/playwright install --with-deps chromium"
log "Playwright Chromium installed"

# ── 6. Node dependencies + frontend build ──────────────────────────
log "Installing Node dependencies + building frontend..."
su - "$DEPLOY_USER" -c "cd $PROJECT_DIR/frontend && npm install && npm run build"
log "Frontend built → $PROJECT_DIR/frontend/build/"

# ── 7. Create data directories ─────────────────────────────────────
mkdir -p "$PROJECT_DIR/Data-dump" "$PROJECT_DIR/Phase2-Dump" "$PROJECT_DIR/Debug-dump" "$PROJECT_DIR/cookies"
# Must exist before the service starts: systemd bind-mounts it writable
# (ReadWritePaths) while the rest of Bot/ stays read-only.
[[ -f "$PROJECT_DIR/Bot/selector_cache.json" ]] || echo '{}' > "$PROJECT_DIR/Bot/selector_cache.json"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$PROJECT_DIR/Data-dump" "$PROJECT_DIR/Phase2-Dump" "$PROJECT_DIR/Debug-dump" "$PROJECT_DIR/cookies"
chown "$DEPLOY_USER:$DEPLOY_USER" "$PROJECT_DIR/Bot/selector_cache.json"
log "Data directories created"

# ── 8. nginx ───────────────────────────────────────────────────────
log "Configuring nginx..."
# Remove default site
rm -f /etc/nginx/sites-enabled/default

# nginx (www-data) must be able to *traverse* into the home-dir web root.
# Home dirs are 0750 by default → 403. Grant execute (traverse) on each parent.
chmod o+x /home "/home/$DEPLOY_USER" "$(dirname "$PROJECT_DIR")" "$PROJECT_DIR" 2>/dev/null || true

# Install our config
cp "$PROJECT_DIR/deploy/nginx.conf" /etc/nginx/sites-available/trawlbase
ln -sf /etc/nginx/sites-available/trawlbase /etc/nginx/sites-enabled/trawlbase

# Test and reload
nginx -t && systemctl reload nginx
log "nginx configured and running"

# ── 9. systemd ─────────────────────────────────────────────────────
log "Setting up systemd service..."
cp "$PROJECT_DIR/deploy/trawlbase.service" /etc/systemd/system/trawlbase.service
systemctl daemon-reload
systemctl enable trawlbase
log "systemd service installed (not started — configure .env first)"

# ── 10. Done ───────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}  Trawlbase installed!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Set your DeepSeek API key and analytics password:"
echo -e "     ${YELLOW}nano $PROJECT_DIR/.env${NC}"
echo "     (ANALYTICS_PASSWORD gates the dashboard at stats.trawlbase.com)"
echo ""
echo "  2. (Optional) Add CORS origins if frontend is on a different domain:"
echo "     CORS_ORIGINS=https://your-domain.com"
echo ""
echo "  3. Start the backend:"
echo -e "     ${YELLOW}systemctl start trawlbase${NC}"
echo ""
echo "  4. Check it's running:"
echo -e "     ${YELLOW}systemctl status trawlbase${NC}"
echo ""
echo "  5. Point DNS at this box + get SSL (see deploy/DEPLOY.md for Namecheap steps):"
echo -e "     ${YELLOW}sudo certbot --nginx -d trawlbase.com -d www.trawlbase.com -d stats.trawlbase.com${NC}"
echo ""
echo "  6. Tail logs:"
echo -e "     ${YELLOW}journalctl -u trawlbase -f${NC}"
echo ""
