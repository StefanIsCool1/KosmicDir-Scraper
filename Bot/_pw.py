"""
Playwright backend selector — single point for the whole scraper.

Prefers `patchright`, a drop-in patched Playwright that closes the
`Runtime.enable` Chrome-DevTools-Protocol leak that DataDome, Cloudflare, and
similar anti-bot systems use to fingerprint automation. That leak lives in the
DevTools protocol layer, NOT in page JavaScript, so `playwright-stealth`
(which only rewrites JS-visible properties) cannot patch it — patchright is the
only thing here that does. Falls back to stock Playwright when patchright isn't
installed, so the scraper runs either way.

To turn on the stronger backend (recommended for DataDome / Cloudflare sites):

    pip install patchright
    patchright install chromium

No code changes are needed afterwards — every launch site imports `sync_playwright`
from this module, so it picks patchright up automatically on the next run.

`IS_PATCHRIGHT` is exported so callers can skip stacking `playwright-stealth` on
top of patchright (patchright already applies its own, more careful patches;
layering the stealth plugin re-introduces detectable modifications).
"""

try:
    from patchright.sync_api import sync_playwright, Playwright  # noqa: F401
    IS_PATCHRIGHT = True
except ImportError:  # patchright not installed — use stock Playwright
    from playwright.sync_api import sync_playwright, Playwright  # noqa: F401
    IS_PATCHRIGHT = False
