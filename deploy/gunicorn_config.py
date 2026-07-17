"""Gunicorn config for Trawlbase production server.

Usage:
    gunicorn -c deploy/gunicorn_config.py app:app
"""

import os

# Bind to localhost only — nginx proxies from the outside
bind = "127.0.0.1:5000"

# One worker is enough for a mini PC. Playwright spawns its own subprocesses.
# Thread-based workers handle SSE streaming better than sync workers.
# Each open stream pins one thread: a run holds its progress SSE, and Live View
# adds a second long-lived frame SSE, so headroom matters. gthread threads are
# cheap — 16 leaves plenty for those plus normal API calls.
worker_class = "gthread"
threads = 16
workers = 1

# Timeouts — scraping can take a while, especially Phase 2 enrichment
timeout = 600  # 10 minutes
graceful_timeout = 30

# Logging
accesslog = "-"          # stdout
errorlog = "-"           # stderr
loglevel = "info"

# Don't daemonize — let systemd manage the process
daemon = False

# Environment
raw_env = [
    f"OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES",
]
