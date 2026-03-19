"""
Debug logging for the directory scraper.

Usage:
    from debug import debug

    debug.log("BROWSER", "Navigated to https://example.com")
    debug.log("SEARCH", "Found 3 search inputs", data={"inputs": [...]})
    debug.log("PARSE", "Card detection failed", level="warn")

Debug mode is OFF by default. Enable it via:
    debug.enabled = True

When disabled, all debug.log() calls are no-ops (zero overhead).
When enabled, messages are stored in debug.entries and printed to console.
"""

import time
import json as _json


class DebugLogger:
    """Centralized debug logger with categorized, timestamped entries."""

    # Categories for filtering
    CATEGORIES = {
        "NAV",       # Navigation — find_directory_url, page clicks
        "SEARCH",    # Search strategy — trigger_search, form detection
        "SCROLL",    # Scrolling — adaptive scroll, infinite scroll detection
        "PAGE",      # Pagination — Next/Load More/category iteration
        "CAPTURE",   # Response capture — JSON/HTML interception
        "IFRAME",    # Iframe detection
        "PARSE",     # HTML parsing — selector learning, card detection, regex fallback
        "DETAIL",    # Detail page crawling
        "CLEAN",     # Cleaning and normalization
        "BROWSER",   # Browser lifecycle — launch, close, errors
    }

    def __init__(self):
        self.enabled = False
        self.entries = []
        self._start_time = None

    def reset(self):
        """Clear all entries and reset timer. Call at the start of each scrape."""
        self.entries = []
        self._start_time = time.time()

    def log(self, category: str, message: str, data=None, level: str = "info"):
        """Log a debug message.

        Args:
            category: One of the CATEGORIES (NAV, SEARCH, PARSE, etc.)
            message: Human-readable description of what happened
            data: Optional dict/list of extra context (selectors found, counts, etc.)
            level: "info", "warn", or "error"
        """
        if not self.enabled:
            return

        elapsed = round(time.time() - self._start_time, 2) if self._start_time else 0

        entry = {
            "time": elapsed,
            "category": category,
            "level": level,
            "message": message,
        }
        if data is not None:
            entry["data"] = data

        self.entries.append(entry)

        # Also print to console with prefix
        prefix = f"[DEBUG {elapsed:>7.2f}s {category:<8}]"
        level_marker = "" if level == "info" else f" [{level.upper()}]"
        print(f"{prefix}{level_marker} {message}")
        if data is not None:
            try:
                print(f"{'':>30} {_json.dumps(data, default=str)[:500]}")
            except Exception:
                print(f"{'':>30} {str(data)[:500]}")

    def get_entries(self) -> list:
        """Return all debug entries (for sending to frontend)."""
        return self.entries

    def get_summary(self) -> dict:
        """Return a summary of the debug session."""
        if not self.entries:
            return {"total_entries": 0}

        total_time = self.entries[-1]["time"] if self.entries else 0
        by_category = {}
        warnings = 0
        errors = 0
        for e in self.entries:
            cat = e["category"]
            by_category[cat] = by_category.get(cat, 0) + 1
            if e["level"] == "warn":
                warnings += 1
            elif e["level"] == "error":
                errors += 1

        return {
            "total_entries": len(self.entries),
            "total_time_seconds": total_time,
            "by_category": by_category,
            "warnings": warnings,
            "errors": errors,
        }


# Global singleton — import and use from anywhere
debug = DebugLogger()
