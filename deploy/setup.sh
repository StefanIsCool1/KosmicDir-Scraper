#!/usr/bin/env bash
# ------------------------------------------------------------------
# Trawlbase — one-command setup for a fresh Ubuntu/Debian mini PC.
#
# Run as root (or with sudo):
#   sudo bash deploy/setup.sh
#
# What it does:
#   1. Installs system packages (Python 3, Node.js, nginx, chromium deps)
#   2. Creates a dedicated 'trawlbase' user
#   3. Clones (or copies) the project into /home/trawlbase/KosmicDir-Scraper
#   4. Installs Python + Node dependencies
#   5. Installs Playwright's Chromium
#   6. Builds the React frontend
#   7. Configures nginx + systemd
#   8. Prints next steps (env, Cloudflare Tunnel, start)
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

PROJECT_DIR="/home/trawlbase/KosmicDir-Scraper"
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

log "System packages installed"

# ── 2. Create trawlbase user ───────────────────────────────────────
if ! id -u trawlbase &>/dev/null; then
    useradd -m -s /bin/bash trawlbase
    log "Created user 'trawlbase'"
else
    log "User 'trawlbase' already exists"
fi

# ── 3. Copy project files ──────────────────────────────────────────
log "Copying project to $PROJECT_DIR ..."
mkdir -p "$PROJECT_DIR"
cp -r "$REPO_ROOT"/* "$PROJECT_DIR/"
cp "$REPO_ROOT"/.env.example "$PROJECT_DIR"/.env 2>/dev/null || touch "$PROJECT_DIR/.env"
chown -R trawlbase:trawlbase /home/trawlbase
log "Project files in place"

# ── 4. Python dependencies ─────────────────────────────────────────
log "Installing Python dependencies..."
su - trawlbase -c "cd $PROJECT_DIR && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
log "Python packages installed"

# ── 5. Playwright Chromium ─────────────────────────────────────────
log "Installing Playwright Chromium (this downloads ~150 MB)..."
su - trawlbase -c "cd $PROJECT_DIR && .venv/bin/playwright install --with-deps chromium"
log "Playwright Chromium installed"

# ── 6. Node dependencies + frontend build ──────────────────────────
log "Installing Node dependencies + building frontend..."
su - trawlbase -c "cd $PROJECT_DIR/frontend && npm install && npm run build"
log "Frontend built → $PROJECT_DIR/frontend/build/"

# ── 7. Create data directories ─────────────────────────────────────
mkdir -p "$PROJECT_DIR/Data-dump" "$PROJECT_DIR/Phase2-Dump" "$PROJECT_DIR/cookies"
chown -R trawlbase:trawlbase "$PROJECT_DIR/Data-dump" "$PROJECT_DIR/Phase2-Dump" "$PROJECT_DIR/cookies"
log "Data directories created"

# ── 8. nginx ───────────────────────────────────────────────────────
log "Configuring nginx..."
# Remove default site
rm -f /etc/nginx/sites-enabled/default

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
echo "  1. Set your DeepSeek API key:"
echo -e "     ${YELLOW}nano $PROJECT_DIR/.env${NC}"
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
echo "  5. Set up Cloudflare Tunnel for public access:"
echo -e "     ${YELLOW}cat $PROJECT_DIR/deploy/cloudflare-tunnel.md${NC}"
echo ""
echo "  6. Tail logs:"
echo -e "     ${YELLOW}journalctl -u trawlbase -f${NC}"
echo ""
