# Deploying Trawlbase to the VPS

The production box is a plain VPS with a public IP, so there's **no Cloudflare
Tunnel** — DNS points straight at it and nginx terminates TLS. (`cloudflare-tunnel.md`
is only kept for the no-public-IP / home-server scenario.)

| Thing | Value |
|---|---|
| Server | `stefan@38.49.215.122` |
| Project dir | `/home/stefan/Projects/TrawlBase` |
| Service user | `stefan` |
| systemd unit | `trawlbase` |
| Domains | `trawlbase.com`, `www.trawlbase.com`, `stats.trawlbase.com` |

`stats.trawlbase.com` serves the **same** build; `frontend/src/main.jsx` detects the
`stats.` hostname and renders only the analytics dashboard.

---

## 1. Passwordless SSH (do this first)

You currently log in with a password and have no local key. Fix that so `rsync`
and `sync.sh` don't prompt every time.

```bash
# On your Mac — generate a key (press Enter for no passphrase, or set one)
ssh-keygen -t ed25519 -C "trawlbase-vps"

# Copy it to the server (this one time asks for your password)
ssh-copy-id stefan@38.49.215.122
# No ssh-copy-id on macOS? →
#   cat ~/.ssh/id_ed25519.pub | ssh stefan@38.49.215.122 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys'
```

Add a short alias so you can type `ssh trawlbase`. Append to `~/.ssh/config`:

```
Host trawlbase
    HostName 38.49.215.122
    User stefan
```

Test: `ssh trawlbase 'echo ok'` should print `ok` with no password.

---

## 2. Namecheap DNS

Namecheap → **Domain List** → **Manage** (trawlbase.com) → **Advanced DNS**.

1. Under **Nameservers**, make sure it's set to **Namecheap BasicDNS** (not
   "Custom DNS" or a redirect) — otherwise Advanced DNS records are ignored.
2. **Delete** the two records Namecheap adds by default: the `CNAME` `www →
   parkingpage.namecheap.com` and the `URL Redirect` on `@`. They'll fight your
   A records.
3. Add these **A Records** (TTL: Automatic):

   | Type | Host | Value | Purpose |
   |---|---|---|---|
   | A Record | `@` | `38.49.215.122` | trawlbase.com |
   | A Record | `www` | `38.49.215.122` | www.trawlbase.com |
   | A Record | `stats` | `38.49.215.122` | stats.trawlbase.com |

DNS takes anywhere from a few minutes to a couple hours. Check with:

```bash
dig +short trawlbase.com stats.trawlbase.com
# both should return 38.49.215.122 before you run certbot
```

---

## 3. First-time server provisioning

If the box isn't set up yet, push the code and run the installer once.

```bash
# From your Mac — push code up (skip build/restart, nothing's running yet)
deploy/sync.sh --no-build --no-restart

# On the server — installs packages, venv, Playwright, builds UI, wires
# nginx + systemd, and fixes home-dir permissions for nginx.
ssh trawlbase
cd ~/Projects/TrawlBase
sudo bash deploy/setup.sh
```

Then set secrets and open the firewall:

```bash
nano ~/Projects/TrawlBase/.env      # DEEPSEEK_API_KEY + ANALYTICS_PASSWORD (don't leave the default!)

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'         # ports 80 + 443
sudo ufw enable

sudo systemctl start trawlbase
sudo systemctl status trawlbase     # should be active (running)
```

> **Why the app can't be `ProtectHome`'d:** it lives under `/home/stefan`, so the
> systemd unit sets `ProtectHome=no` and relies on `ProtectSystem=strict` +
> `ReadWritePaths` instead. And nginx (`www-data`) needs *execute* on every
> parent dir to reach `frontend/build` — `setup.sh` runs the `chmod o+x` for you.

---

## 4. SSL (Let's Encrypt)

Once `dig` shows all three names resolving to the VPS:

```bash
sudo certbot --nginx -d trawlbase.com -d www.trawlbase.com -d stats.trawlbase.com
```

Certbot edits the nginx config in place to add `listen 443` blocks and sets up
auto-renewal. Choose "redirect HTTP → HTTPS" when it asks.

---

## 5. Day-to-day: pushing changes

From your Mac, after editing code:

```bash
deploy/sync.sh              # builds frontend, rsyncs, restarts backend
deploy/sync.sh -n           # dry run — see what would change first
deploy/sync.sh --no-build   # backend-only edit, skip the UI build
deploy/sync.sh --deps       # also re-run pip install (requirements.txt changed)
```

`--delete` mirrors local → server, but the script **never** touches server-owned
paths: `.env`, `Data-dump/` (incl. `analytics.db`), `Phase2-Dump/`, `Debug-dump/`,
`cookies/`, `.venv/`, and `Bot/selector_cache.json` are all excluded.

### Make the restart non-interactive

`sync.sh` restarts the service over SSH, which needs `sudo`. To avoid a password
prompt on every deploy, add a narrow sudoers rule **on the server**:

```bash
echo 'stefan ALL=(root) NOPASSWD: /usr/bin/systemctl restart trawlbase, /usr/bin/systemctl status trawlbase' \
  | sudo tee /etc/sudoers.d/trawlbase-restart
sudo chmod 440 /etc/sudoers.d/trawlbase-restart
```

(Confirm the systemctl path with `which systemctl` — it's `/usr/bin/systemctl` on
Ubuntu/Debian. Adjust if yours differs.)

---

## 6. Troubleshooting

| Symptom | Check |
|---|---|
| `502 Bad Gateway` | Backend down: `sudo systemctl status trawlbase`, `journalctl -u trawlbase -f` |
| `403 Forbidden` on `/` | nginx can't traverse into `frontend/build`: `sudo chmod o+x /home/stefan /home/stefan/Projects /home/stefan/Projects/TrawlBase` |
| certbot fails | DNS not propagated yet, or port 80 blocked (`sudo ufw status`) |
| Analytics 500 / no data | `.env` missing `ANALYTICS_PASSWORD`; DB is `Data-dump/analytics.db` |
| `stats.` shows the main site | Old build deployed — rebuild + `deploy/sync.sh`; `main.jsx` does the host split |
| SSE / live scrape stalls | nginx buffering — already off in `nginx.conf`; confirm you deployed the current one |
