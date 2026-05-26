"""
Phase 0 — Pre-Flight Qualification

One lightweight curl_cffi request per candidate. Rejects dead, blocked,
login-gated, thin, and obviously-not-a-directory URLs before classification.

Runs in parallel (ThreadPoolExecutor) using Phase 2's TLS-impersonated fetcher.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Reuse Phase 2's TLS-fingerprinted HTTP fetcher (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Phase2Bot.page_fetcher import fetch_page  # type: ignore  # noqa: E402


MIN_BODY_BYTES = 5_000  # below this, the page is a parked domain or blank
MIN_DIRECTORY_SIGNALS = 2

# Keyword signals that hint a page is a directory/listing. Bag-of-words on
# the visible text — fast but coarse. A real classification still happens
# in classifier.py via structural detection.
DIRECTORY_SIGNALS = [
    "member", "members", "directory", "listing", "listings",
    "search", "find a", "browse",
    "results", "company", "companies",
    "provider", "providers", "doctor", "doctors", "dentist", "dentists",
    "restaurant", "restaurants", "attorney", "attorneys", "lawyer", "lawyers",
    "contractor", "contractors", "vendor", "vendors",
    "association", "associations", "chamber", "registry", "roster",
]


def _qualify_soup(soup) -> tuple[bool, str | None]:
    """Apply reject rules to a parsed soup. Returns (passed, reason_if_rejected)."""
    html = str(soup)
    if len(html) < MIN_BODY_BYTES:
        return False, "thin_content"

    # Login wall — strongest single signal. Phase 1 handles interactive
    # login flows; in batch discovery we just skip these.
    if soup.find("input", attrs={"type": "password"}):
        return False, "login_wall"

    # Directory keyword density — case-insensitive substring count
    text = soup.get_text(separator=" ").lower()
    signal_count = sum(1 for kw in DIRECTORY_SIGNALS if kw in text)
    if signal_count < MIN_DIRECTORY_SIGNALS:
        return False, "no_directory_signals"

    return True, None


def preflight_one(candidate: dict) -> dict:
    """Qualify a single candidate URL.

    Returns the candidate dict augmented with status / reason / soup / final_url.
    status is "passed" or "rejected".
    """
    url = candidate["url"]

    try:
        soup, final_url = fetch_page(url)
    except Exception:
        return {**candidate, "status": "rejected", "reason": "fetch_failed"}

    if soup is None:
        return {**candidate, "status": "rejected", "reason": "fetch_failed"}

    passed, reason = _qualify_soup(soup)
    if not passed:
        return {**candidate, "status": "rejected", "reason": reason}

    return {
        **candidate,
        "status": "passed",
        "reason": None,
        "soup": soup,
        "final_url": final_url or url,
    }


def preflight_all(candidates: list[dict], event_cb=None,
                   max_workers: int = 8) -> tuple[list[dict], list[dict]]:
    """Run preflight on all candidates in parallel.

    Returns (passed, rejected) lists. Passed entries carry their soup so
    the classifier can reuse it without re-fetching.
    """
    if not candidates:
        return [], []

    passed: list[dict] = []
    rejected: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(preflight_one, c): c for c in candidates}
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as e:
                src = futures[fut]
                result = {**src, "status": "rejected", "reason": f"worker_error: {e}"}

            if event_cb:
                event_cb({
                    "type": "preflight_result",
                    "url": result["url"],
                    "status": result["status"],
                    "reason": result.get("reason"),
                })

            if result["status"] == "passed":
                passed.append(result)
            else:
                rejected.append(result)

    return passed, rejected
