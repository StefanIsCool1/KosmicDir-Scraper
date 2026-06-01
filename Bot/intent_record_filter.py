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
                    scope: str) -> list[bool]:
    """Return a keep-flag per record. Fail-open: any error → keep everything."""
    alias_hint = f" (also known as: {', '.join(aliases[:5])})" if aliases else ""

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

{scope_rule}

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
        flags = _classify_batch(recs, canonical, aliases, scope)
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
