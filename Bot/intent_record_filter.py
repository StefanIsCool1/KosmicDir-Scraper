"""
Phase 1 — Record-level intent filter.

After extraction, trims a directory's member list down to the user's actual
target. Only the Agent (/discover) path supplies an `intent` dict; Playground
modes pass intent=None and this is a no-op, so Direct/Auto/CSV scrapes are
bit-for-bit unchanged.

Scope (set by the Phase 0 scope gate, see DiscoveryBot/intent.py +
Bot/intent_filter.py) tunes how aggressively we drop:
  - "specialist": keep only businesses that clearly do the trade; drop general
    contractors / remodelers that don't obviously specialize in it.
  - "inclusive":  keep specialists AND general contractors / remodelers /
    builders who plausibly do the work; drop only clearly-unrelated businesses.

FAIL-OPEN is the governing rule. We ask the model to name only the rows it is
CONFIDENT are non-matches; everything else is kept. A record too thin to judge
(e.g. just a company name with no obvious trade, which is common on GrowthZone
cards that expose no category/description) is therefore KEPT, not dropped —
dropping a real deck builder is worse than keeping a few extra rows.

Batched (one LLM call per ~30 records) and cached by (name, category, scope) so
the same company is never classified twice within a process.
"""

import json
import re

from llm import ask

# How many records per classification call. Small records, so a few dozen fit
# comfortably; keeps us to ~20 calls on a 600-member association.
_BATCH_SIZE = 30
# Truncate long descriptions so one batch stays within a cheap token budget.
_DESC_TRUNCATE = 160

# (name_lower, category_lower, scope) -> keep(bool). Module-level so repeated
# companies (same firm listed under several categories, or across directories
# in one run) reuse the decision.
_RECORD_CACHE: dict[tuple, bool] = {}

# --- Location filtering (deterministic, no LLM) ---
_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
# High-precision state parsing: a state code immediately before a ZIP, or a
# trailing ", XX". A bare \b[A-Z]{2}\b scan would read "123 Main CT" (Court)
# as Connecticut and wrongly drop the record.
_ADDR_STATE_ZIP_RE = re.compile(r'\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b')
_ADDR_TRAILING_STATE_RE = re.compile(r',\s*([A-Z]{2})\s*$')


def _filter_by_location(records: list[dict], intent: dict) -> tuple[list[dict], int]:
    """Drop a record ONLY when its address contains a confidently-parsed US
    state that is NOT one of the intent's states.

    Fail-open, same governing rule as the industry filter: no address, or no
    parseable state, means KEEP. Returns (kept_records, dropped_count).
    """
    want = {(s or "").strip().upper() for s in (intent.get("location_states") or [])}
    want &= _US_STATE_CODES
    if not want:
        return records, 0

    kept: list[dict] = []
    dropped = 0
    for r in records:
        addr = " ".join(
            str(r.get(k) or "") for k in ("street_address", "mailing_address")
        ).strip()
        found = set(_ADDR_STATE_ZIP_RE.findall(addr)) & _US_STATE_CODES
        if not found:
            m = _ADDR_TRAILING_STATE_RE.search(addr)
            if m and m.group(1) in _US_STATE_CODES:
                found = {m.group(1)}
        if found and not (found & want):
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def reset_record_cache():
    """Clear the classification cache. Call between distinct runs if you want
    to force re-classification."""
    _RECORD_CACHE.clear()


def _cache_key(record: dict, scope: str) -> tuple:
    name = (record.get("company_name") or "").strip().lower()
    cat = (record.get("category") or "").strip().lower()
    return (name, cat, scope)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _classify_batch(records: list[dict], canonical: str, aliases: list[str],
                    scope: str, location_states: list | None = None) -> list[bool]:
    """Return a keep-flag per record. Fail-open: any error → keep everything."""
    alias_hint = f" (also known as: {', '.join(aliases[:5])})" if aliases else ""
    location_line = ""
    if location_states:
        location_line = (
            f"\nThe user's target location: {', '.join(location_states[:8])}. "
            f"Location is context only — do NOT drop rows for location alone; "
            f"a separate deterministic filter handles that."
        )

    if scope == "specialist":
        scope_rule = (
            f"Drop rows that are NOT clearly {canonical}. Drop general contractors, "
            f"remodelers, or builders that do not obviously specialize in {canonical}. "
            f"Keep only businesses that clearly do {canonical}."
        )
    else:
        scope_rule = (
            f"KEEP {canonical} specialists AND general contractors / remodelers / "
            f"builders / home-improvement firms that plausibly do {canonical} work. "
            f"Drop ONLY rows that are clearly unrelated to {canonical} — e.g. "
            f"roofing-only, HVAC, plumbing, electrical-only, insurance, marketing, "
            f"printing, banks, restaurants, law firms."
        )

    lines = []
    for i, rec in enumerate(records, start=1):
        name = (rec.get("company_name") or "").strip() or "(no name)"
        cat = (rec.get("category") or "").strip() or "(none)"
        desc = (rec.get("description") or "").strip()
        if len(desc) > _DESC_TRUNCATE:
            desc = desc[:_DESC_TRUNCATE] + "…"
        desc = desc or "(none)"
        lines.append(f"{i}. name={name} | category={cat} | description={desc}")
    enumerated = "\n".join(lines)

    prompt = f"""You are filtering a business directory down to {canonical}{alias_hint}.

{scope_rule}{location_line}

IMPORTANT: Only drop rows you are CONFIDENT are non-matches. If a row has too
little information to judge (e.g. just a company name with no obvious trade), DO
NOT drop it — keep it.

Businesses:
{enumerated}

Return ONLY a JSON object — no markdown fences, no explanation:
{{"drop": [<1-based row numbers you are confident are NOT {canonical}>]}}"""

    try:
        raw = ask(prompt, max_tokens=400)
    except Exception as e:
        print(f"  Intent record filter: LLM call failed ({str(e)[:60]}) — keeping batch")
        return [True] * len(records)

    try:
        decision = json.loads(_strip_fences(raw))
        drop_raw = decision.get("drop") if isinstance(decision, dict) else None
        drop = {int(x) for x in drop_raw} if isinstance(drop_raw, list) else set()
    except (json.JSONDecodeError, ValueError, TypeError):
        print("  Intent record filter: non-JSON response — keeping batch")
        return [True] * len(records)

    # Keep row i (1-based) unless the model explicitly flagged it to drop.
    return [(i not in drop) for i in range(1, len(records) + 1)]


def filter_records_by_intent(records: list[dict], intent: dict | None) -> list[dict]:
    """Trim `records` to those matching the user's intent.

    No-op when intent is None/empty or has no industry (Playground paths).
    Fail-open: on any classification failure, the affected records are kept.
    """
    if not intent or not records:
        return records
    canonical = (intent.get("industry_canonical") or "").strip()
    if not canonical:
        return records

    scope = (intent.get("scope") or "inclusive").lower()
    if scope not in ("specialist", "inclusive"):
        scope = "inclusive"
    aliases = intent.get("industry_aliases") or []
    location_states = [s for s in (intent.get("location_states") or []) if s]

    # Deterministic location pass first — "dentists in Austin" scraped off a
    # national directory must not return every state. Fail-open: records
    # without a confidently-parsed state are kept.
    records, loc_dropped = _filter_by_location(records, intent)
    if loc_dropped:
        print(f"  Intent record filter: dropped {loc_dropped} out-of-state record(s)")
    if not records:
        return records

    keep_by_index: dict[int, bool] = {}
    to_classify: list[tuple[int, dict]] = []
    for idx, rec in enumerate(records):
        key = _cache_key(rec, scope)
        if key in _RECORD_CACHE:
            keep_by_index[idx] = _RECORD_CACHE[key]
        else:
            to_classify.append((idx, rec))

    for batch in _chunks(to_classify, _BATCH_SIZE):
        recs = [r for _, r in batch]
        flags = _classify_batch(recs, canonical, aliases, scope,
                                location_states=location_states)
        for (idx, rec), keep in zip(batch, flags):
            keep_by_index[idx] = keep
            _RECORD_CACHE[_cache_key(rec, scope)] = keep

    kept = [r for idx, r in enumerate(records) if keep_by_index.get(idx, True)]
    dropped = len(records) - len(kept)
    print(
        f"  Intent record filter [{scope}]: kept {len(kept)}/{len(records)} "
        f"for '{canonical}' (dropped {dropped})"
    )
    return kept
