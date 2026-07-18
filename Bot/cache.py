"""
Selector cache management.
Stores learned CSS selectors per domain so Haiku is only called once per site ever.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from config import MAX_CACHED_LAYOUTS, SELECTOR_CACHE_FILENAME

# Module-level cache dict
_selector_cache = {}

# Schema keys that are not field selectors — everything else in a flat
# (business/person) schema is a field key and participates in the layout
# fingerprint.
_NON_FIELD_KEYS = {"card_selector", "entity_type", "name_field",
                   "fingerprint", "learned_at"}

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


# --- LAYOUT FINGERPRINTS (UNIVERSALITY_PLAN Phase 2, R5) ---
# A domain with two listing layouts (e.g. a card grid and a table view)
# used to thrash the single slot and silently lose one schema. Entries now
# carry {fingerprint, learned_at}; the most recently validated schema is
# the primary under the plain domain key (so every legacy reader keeps
# working) and alternates live side by side under "layouts_<domain>".
# Legacy fingerprint-less entries read as the primary and get their
# fingerprint computed on the fly — no mass invalidation.

def layout_fingerprint(selectors: dict) -> str | None:
    """Stable id for a learned layout: hash(card_selector + sorted field
    keys). None when the schema has no card_selector (unusable — those are
    never cached anyway)."""
    if not isinstance(selectors, dict):
        return None
    card = str(selectors.get("card_selector") or "").strip()
    if not card:
        return None
    if isinstance(selectors.get("fields"), list):
        # Dynamic schema: field keys live in fields[].
        keys = sorted(str(f.get("key")) for f in selectors["fields"]
                      if isinstance(f, dict) and f.get("key"))
    else:
        keys = sorted(k for k, v in selectors.items()
                      if v and k not in _NON_FIELD_KEYS)
    payload = card + "|" + ",".join(keys)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _layouts_key(domain: str) -> str:
    return f"layouts_{domain}"


def _fp(entry: dict) -> str | None:
    return entry.get("fingerprint") or layout_fingerprint(entry)


def get_cached_layouts(domain: str) -> list[dict]:
    """All cached layout schemas for a domain, primary first."""
    layouts: list[dict] = []
    primary = _selector_cache.get(domain)
    if isinstance(primary, dict):
        layouts.append(primary)
    primary_fp = _fp(primary) if isinstance(primary, dict) else None
    for alt in _selector_cache.get(_layouts_key(domain)) or []:
        if isinstance(alt, dict) and _fp(alt) != primary_fp:
            layouts.append(alt)
    return layouts


def set_cached_selectors(domain: str, selectors: dict):
    """Store selectors for a domain and persist to disk.

    The new schema becomes the primary; a previous primary with a
    DIFFERENT fingerprint is demoted to the layouts list instead of being
    lost, so both listing layouts of a two-layout domain stay cached.
    Re-caching an already-known layout (same fingerprint) just promotes it."""
    fp = layout_fingerprint(selectors)
    if fp:
        selectors = {**selectors, "fingerprint": fp,
                     "learned_at": selectors.get("learned_at")
                     or datetime.now(timezone.utc).isoformat()}
    old = _selector_cache.get(domain)
    if isinstance(old, dict) and fp:
        old_fp = _fp(old)
        if old_fp and old_fp != fp:
            alts = [a for a in _selector_cache.get(_layouts_key(domain)) or []
                    if isinstance(a, dict) and _fp(a) not in (fp, old_fp)]
            alts.insert(0, old)
            _selector_cache[_layouts_key(domain)] = alts[:MAX_CACHED_LAYOUTS - 1]
    _selector_cache[domain] = selectors
    save_selector_cache()
    print(f"  Learned and cached selectors for {domain}")


def remove_cached_layout(domain: str, selectors: dict):
    """Scrub ONE layout (matched by fingerprint) wherever it is stored —
    used when a just-learned schema fails validation. If it was the
    primary, the newest alternate is promoted, which restores the
    previously demoted schema without a separate save/restore dance."""
    fp = _fp(selectors or {})
    if not fp:
        return
    changed = False
    primary = _selector_cache.get(domain)
    alts = [a for a in _selector_cache.get(_layouts_key(domain)) or []
            if isinstance(a, dict)]
    if isinstance(primary, dict) and _fp(primary) == fp:
        del _selector_cache[domain]
        changed = True
        if alts:
            _selector_cache[domain] = alts.pop(0)
    kept = [a for a in alts if _fp(a) != fp]
    if len(kept) != len(alts):
        changed = True
    if kept:
        _selector_cache[_layouts_key(domain)] = kept
    else:
        _selector_cache.pop(_layouts_key(domain), None)
    if changed:
        save_selector_cache()
        print(f"  Removed layout {fp} for {domain}")


def delete_cached_selectors(domain: str):
    """Remove ALL cached selectors for a domain — primary and alternate
    layouts (e.g. when extraction was judged garbage)."""
    removed = False
    for key in (domain, _layouts_key(domain)):
        if key in _selector_cache:
            del _selector_cache[key]
            removed = True
    if removed:
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


# --- INTENT SUB-PAGE NAV CACHE ---
# Stored under "intent_nav_<domain>" keys as {canonical: [hrefs...]} in the
# same selector_cache.json. Lets the intent sub-page crawler skip the landing-
# page detect + LLM pick on a repeat run for the same domain+industry — the
# same ~one-AI-call-per-domain discipline as the selector cache.

def get_cached_intent_subpages(domain: str, canonical: str) -> list | None:
    """Get cached intent-matched seed sub-page hrefs, or None if not cached."""
    entry = _selector_cache.get(f"intent_nav_{domain}")
    if isinstance(entry, dict):
        return entry.get((canonical or "").lower())
    return None


def set_cached_intent_subpages(domain: str, canonical: str, hrefs: list):
    """Cache the intent-matched seed sub-page hrefs for a domain+industry."""
    key = f"intent_nav_{domain}"
    entry = _selector_cache.get(key)
    if not isinstance(entry, dict):
        entry = {}
    entry[(canonical or "").lower()] = hrefs
    _selector_cache[key] = entry
    save_selector_cache()
    print(f"  Cached {len(hrefs)} intent sub-page seeds for {domain} "
          f"('{canonical}')")


# Load cache on module import
load_selector_cache()