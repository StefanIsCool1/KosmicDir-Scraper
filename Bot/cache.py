"""
Selector cache management.
Stores learned CSS selectors per domain so Haiku is only called once per site ever.
"""

import json
import os
from config import SELECTOR_CACHE_FILENAME

# Module-level cache dict
_selector_cache = {}

# Cache file lives next to this script
SELECTOR_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    SELECTOR_CACHE_FILENAME
)


def load_selector_cache():
    """Load cached selectors from disk on startup."""
    global _selector_cache
    if os.path.exists(SELECTOR_CACHE_FILE):
        with open(SELECTOR_CACHE_FILE, "r") as f:
            _selector_cache = json.load(f)
        print(f"Loaded {len(_selector_cache)} cached selector mappings")


def save_selector_cache():
    """Persist selector cache to disk."""
    with open(SELECTOR_CACHE_FILE, "w") as f:
        json.dump(_selector_cache, f, indent=4)


def get_cached_selectors(domain: str) -> dict | None:
    """Get cached selectors for a domain, or None if not cached."""
    return _selector_cache.get(domain)


def set_cached_selectors(domain: str, selectors: dict):
    """Store selectors for a domain and persist to disk."""
    _selector_cache[domain] = selectors
    save_selector_cache()
    print(f"  Learned and cached selectors for {domain}")


def delete_cached_selectors(domain: str):
    """Remove cached selectors for a domain (e.g. when they stop working)."""
    if domain in _selector_cache:
        del _selector_cache[domain]
        save_selector_cache()
        print(f"  Removed stale cached selectors for {domain}")


# --- URL ENUMERATION TEMPLATE CACHE ---
# Stored under "url_enum_<domain>" keys in the same selector_cache.json,
# so we don't need a second file. Plans are static once detected
# (the dropdown options rarely change).

def get_cached_url_template(domain: str) -> dict | None:
    """Get the cached URL-enumeration plan for a domain, or None."""
    return _selector_cache.get(f"url_enum_{domain}")


def set_cached_url_template(domain: str, plan: dict):
    """Cache the URL-enumeration plan for a domain."""
    _selector_cache[f"url_enum_{domain}"] = plan
    save_selector_cache()
    print(f"  Cached URL-enumeration plan for {domain} "
          f"({len(plan.get('values', []))} values)")


# Load cache on module import
load_selector_cache()