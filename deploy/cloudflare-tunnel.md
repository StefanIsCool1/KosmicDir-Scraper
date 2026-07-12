# Cloudflare Tunnel — Public Access Without Port Forwarding

> **Not the current production path.** The VPS has a public IP, so deployment
> uses direct DNS + certbot — see **`DEPLOY.md`**. Keep this only if you ever
> move to a box with no public IP (home server, NAT'd network).


Cloudflare Tunnel gives your mini PC a public URL **without** opening router ports,
exposing your home IP, or dealing with dynamic DNS. It's free.

## Architecture

```
Internet → cloudflared → nginx (localhost:80) → Flask (localhost:5000)
   ↑                       ↑
   your-domain.com         your mini PC
```

## Setup (5 minutes)

### 1. Create a Cloudflare account (free)

https://dash.cloudflare.com/sign-up

### 2. Add your domain to Cloudflare

If you already own a domain, add it to Cloudflare (free plan works).
If you don't have a domain, skip to the "Quick Tunnel" section below — you'll
get a `*.trycloudflare.com` URL instead.

### 3. Install cloudflared on the mini PC

```bash
# Ubuntu / Debian (one-liner)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
```

### 4. Authenticate

```bash
cloudflared tunnel login
```

This opens a browser. Pick your domain. It saves a cert to
`~/.cloudflared/cert.pem`.

### 5. Create the tunnel

```bash
cloudflared tunnel create trawlbase
```

This prints a tunnel ID (e.g., `abcdef12-3456-...`). Keep it.

### 6. Route traffic

```bash
# Point your domain (or subdomain) to the tunnel
cloudflared tunnel route dns trawlbase trawlbase.com
cloudflared tunnel route dns trawlbase www.trawlbase.com
# Analytics dashboard lives on its own subdomain
cloudflared tunnel route dns trawlbase stats.trawlbase.com
```

### 7. Configure the tunnel

Create `/home/trawlbase/.cloudflared/config.yml`:

```yaml
tunnel: <YOUR-TUNNEL-ID>
credentials-file: /home/trawlbase/.cloudflared/<YOUR-TUNNEL-ID>.json

ingress:
  # nginx routes by Host header, so every hostname forwards to the same port —
  # trawlbase.com gets the app, stats.trawlbase.com gets the analytics dashboard.
  - hostname: trawlbase.com
    service: http://localhost:80
  - hostname: www.trawlbase.com
    service: http://localhost:80
  - hostname: stats.trawlbase.com
    service: http://localhost:80
  - service: http_status:404
```

Replace `<YOUR-TUNNEL-ID>` with the ID from step 5.

### 8. Run as a systemd service

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl status cloudflared
```

Done. Your site is now live at `https://scraper.yourdomain.com`.

---

## Quick Tunnel (no domain needed)

If you don't have a domain, use a throwaway `trycloudflare.com` URL:

```bash
cloudflared tunnel --url http://localhost:80
```

This prints a public URL like `https://random-words.trycloudflare.com`.
**It changes every time you restart** — good for testing, not for production.

---

## Updating CORS

If your Cloudflare domain differs from `localhost`, set it in `.env`:

```bash
echo 'CORS_ORIGINS=https://scraper.yourdomain.com' >> /home/trawlbase/KosmicDir-Scraper/.env
sudo systemctl restart trawlbase
```

Without this, CORS errors may block API calls from the frontend (though if
nginx serves both frontend and API from the same domain, CORS is never
triggered — it's only an issue if you host the frontend on a different
domain than the API).

---

## Security notes

- Cloudflare's free tier includes DDoS protection, bot fight mode, and rate limiting
- Add an IP whitelist if you're the only user:
  Cloudflare Dashboard → Security → WAF → Create Rule → `ip.src ne <your-ip>` → Block
- The scraper launches a real Chrome — don't put secrets in scrape targets
- Consider Cloudflare Access (Zero Trust) to put a login gate in front of the app
