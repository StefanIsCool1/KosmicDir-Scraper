"""
Debug logging + run tracing for the directory scraper.

Three kinds of entries, all stamped with seconds elapsed since reset():

    debug.log("SEARCH", "Found 3 search inputs", data={"inputs": [...]})
    debug.decision("NAV", "STAY", "page already shows member entries")
    with debug.span("PAGE", "handle_pagination"):
        ...  # duration recorded on exit

Debug mode is OFF by default. Enable it via:
    debug.enabled = True     (app.py forces this on for /discover runs)
    SCRAPER_DEBUG=1          (env var — CLI runs of Bot/main.py)

When disabled, all calls are no-ops (zero overhead). When enabled, entries
are stored in debug.entries (thread-safe — the Playwright response listener
and idle timers run off-thread) and printed to console. save_report(path)
writes the full trace + summary as JSON — main.py saves one per scrape to
Debug-dump/{domain}_debug.json, app.py saves the Phase 0 trace per
/discover run.
"""

import os
import time
import threading
import json as _json
from contextlib import contextmanager


class DebugLogger:
    """Centralized debug logger with categorized, timestamped entries."""

    # Categories for filtering
    CATEGORIES = {
        "PHASE0",    # Discovery pipeline — intent, DDG search, preflight, classify
        "NAV",       # Navigation — find_directory_url, page clicks
        "SEARCH",    # Search strategy — trigger_search, form detection
        "SCROLL",    # Scrolling — adaptive scroll, infinite scroll detection
        "PAGE",      # Pagination — Next/Load More/category iteration
        "EXPAND",    # AI sub-listing expansion (city/category link crawl)
        "CAPTURE",   # Response capture — JSON/HTML interception
        "IFRAME",    # Iframe detection
        "PARSE",     # HTML parsing — selector learning, card detection, regex fallback
        "DETAIL",    # Detail page crawling
        "CLEAN",     # Cleaning and normalization
        "BROWSER",   # Browser lifecycle — launch, close, errors
    }

    def __init__(self):
        self.enabled = os.environ.get("SCRAPER_DEBUG", "").strip().lower() in ("1", "true", "yes")
        self.entries = []
        self._start_time = time.time() if self.enabled else None
        self._lock = threading.Lock()

    def reset(self):
        """Clear all entries and reset timer. Call at the start of each scrape."""
        with self._lock:
            self.entries = []
            self._start_time = time.time()

    def _elapsed(self) -> float:
        if self._start_time is None:
            self._start_time = time.time()
        return round(time.time() - self._start_time, 2)

    def _add(self, entry: dict):
        with self._lock:
            self.entries.append(entry)

    def _print(self, entry: dict):
        prefix = f"[DEBUG {entry['time']:>7.2f}s {entry['category']:<8}]"
        level = entry.get("level", "info")
        level_marker = "" if level == "info" else f" [{level.upper()}]"
        dur = entry.get("duration_s")
        dur_marker = f" ({dur:.2f}s)" if dur is not None else ""
        print(f"{prefix}{level_marker} {entry['message']}{dur_marker}")
        if entry.get("data") is not None:
            try:
                print(f"{'':>30} {_json.dumps(entry['data'], default=str)[:500]}")
            except Exception:
                print(f"{'':>30} {str(entry['data'])[:500]}")

    def log(self, category: str, message: str, data=None, level: str = "info"):
        """Log a debug action.

        Args:
            category: One of the CATEGORIES (NAV, SEARCH, PARSE, etc.)
            message: Human-readable description of what happened
            data: Optional dict/list of extra context (selectors found, counts, etc.)
            level: "info", "warn", or "error"
        """
        if not self.enabled:
            return

        entry = {
            "time": self._elapsed(),
            "kind": "action",
            "category": category,
            "level": level,
            "message": message,
        }
        if data is not None:
            entry["data"] = data

        self._add(entry)
        self._print(entry)

    def decision(self, category: str, decision: str, reason: str = "", data=None):
        """Record a branch decision the bot took and why.

        Shows up in the trace as kind="decision" so a run can be audited:
        what the bot chose at each fork (stay/click, skip pagination,
        bail out, crawl sub-listings, ...) and the evidence it used.
        """
        if not self.enabled:
            return

        message = f"DECISION: {decision}" + (f" — {reason}" if reason else "")
        entry = {
            "time": self._elapsed(),
            "kind": "decision",
            "category": category,
            "level": "info",
            "message": message,
            "decision": decision,
        }
        if reason:
            entry["reason"] = reason
        if data is not None:
            entry["data"] = data

        self._add(entry)
        self._print(entry)

    @contextmanager
    def span(self, category: str, label: str, data=None):
        """Time a block of work. Records duration_s on exit (even on error).

        Usage:
            with debug.span("SEARCH", "trigger_search"):
                ...
        """
        if not self.enabled:
            yield
            return

        start = time.time()
        try:
            yield
        finally:
            entry = {
                "time": self._elapsed(),
                "kind": "span",
                "category": category,
                "level": "info",
                "message": label,
                "duration_s": round(time.time() - start, 2),
            }
            if data is not None:
                entry["data"] = data
            self._add(entry)
            self._print(entry)

    def get_entries(self) -> list:
        """Return all debug entries (for sending to frontend)."""
        return self.entries

    def get_summary(self) -> dict:
        """Return a summary of the debug session: totals, per-category counts,
        and where the time went (span durations, slowest first)."""
        with self._lock:
            entries = list(self.entries)

        if not entries:
            return {"total_entries": 0}

        total_time = entries[-1]["time"]
        by_category = {}
        durations: dict[str, float] = {}
        warnings = 0
        errors = 0
        decisions = 0
        for e in entries:
            cat = e["category"]
            by_category[cat] = by_category.get(cat, 0) + 1
            if e["level"] == "warn":
                warnings += 1
            elif e["level"] == "error":
                errors += 1
            if e.get("kind") == "decision":
                decisions += 1
            if e.get("duration_s") is not None:
                key = f"{cat}: {e['message']}"
                durations[key] = round(durations.get(key, 0) + e["duration_s"], 2)

        slowest = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)[:15]

        return {
            "total_entries": len(entries),
            "total_time_seconds": total_time,
            "by_category": by_category,
            "decisions": decisions,
            "warnings": warnings,
            "errors": errors,
            "time_spent": dict(slowest),
        }

    def save_report(self, path: str) -> str | None:
        """Write the full trace (summary + entries) to a JSON file.

        Never raises — a broken trace write must not kill a scrape.
        Returns the path on success, None on failure or when disabled.
        """
        if not self.enabled:
            return None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with self._lock:
                report = {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "entries": list(self.entries),
                }
            report["summary"] = self.get_summary()
            with open(path, "w") as f:
                _json.dump(report, f, indent=2, default=str)
            print(f"  Debug trace saved to {path}")
            return path
        except Exception as e:
            print(f"  Failed to save debug trace to {path}: {e}")
            return None


# Global singleton — import and use from anywhere
debug = DebugLogger()
