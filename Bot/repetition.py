"""Structural repetition detection (UNIVERSALITY_PLAN Phase 1).

find_repeated_records(html) locates the page's member-record run WITHOUT
reading class names: per-child signature = tag + depth-capped descendant-tag
multiset + text-length bucket; the winning run is the highest RECORD-DENSITY
run of >=4 near-identical adjacent siblings, not merely the longest — nav
menus and dropdown option lists are often the most repetitive structure on
the page and must lose here.

Class names come back in only at the very end, for selector EMISSION
(stable class > container-anchored path > unstable/hashed class), and the
emitted selector is round-trip validated with select() before being trusted.

Deliberately self-contained: imports config only (html_parser imports this
module for Strategy 2.5, so importing html_parser back would be a cycle —
the few contact regexes are mirrored here instead).
"""

import re
from collections import Counter
from statistics import median

from bs4 import BeautifulSoup
from bs4.element import Tag

from config import (
    CARD_CLASS_HINTS, JUNK_CONTAINER_SELECTORS, JUNK_TAGS, LAYOUT_CLASS_EXACT,
)

# --- Tunables ---
MIN_RUN = 4                 # plan: "largest run of >=4 near-identical adjacent siblings"
SIG_SIMILARITY = 0.8        # ~20% signature variance allowed (premium vs basic cards)
MIN_MEDIAN_TEXT = 15        # same floor as count_visible_results' JS-side guard
MIN_SIGNAL_DENSITY = 0.5    # "at least one contact signal or detail link in the median node"
SIG_DEPTH_CAP = 3           # descendant-tag multiset depth
ROUND_TRIP_SLACK = 1.3      # selector may over-match the run by at most 30%
ANCHOR_DOMINANCE = 0.9      # >=90% of text inside <a> => link list, not records

# Mirrors of html_parser's contact regexes (import would be circular).
_PHONE_RE = re.compile(
    r'(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)[\s.\-]?|\d{3}[\s.\-])\d{3}[\s.\-]?\d{4}(?!\d)'
)
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
_ADDRESS_RE = re.compile(
    r'\d{1,6}\s+[A-Za-z0-9.\s]{2,40}'
    r'(?:St\.?|Street|Ave\.?|Avenue|Blvd\.?|Boulevard|Dr\.?|Drive|Rd\.?|Road|'
    r'Ln\.?|Lane|Way|Ct\.?|Court|Pl\.?|Place|Pkwy\.?|Parkway|Hwy\.?|Highway)\b',
    re.IGNORECASE,
)

_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE
)
_CSS_IDENT_RE = re.compile(r'^-?[A-Za-z_][\w-]*$')
# Generated-CSS class shapes (CSS modules, styled-components, tailwind-jit
# hashes). Usable in a within-page-lifetime selector, never preferred.
_UNSTABLE_CLASS_RE = re.compile(r'^(css|jss|sc|go|_)[-_]?[0-9a-zA-Z]*\d')

_ZEBRA = {"odd", "even", "alt", "alternate", "stripe", "striped"}

# Structural separators that may interleave a card run without breaking it
# (clearfix divs, <hr> rules). An element is a separator when it's one of
# these tags or has neither text nor element children.
_SEPARATOR_TAGS = {"hr", "br"}


def _strip_junk(soup: BeautifulSoup) -> BeautifulSoup:
    """Same semantics as html_parser.strip_junk (mirrored to avoid a module
    cycle): drop junk tags and nav/layout containers, never the page spine."""
    protected = {"html", "body", "main", "article", "section"}
    for tag in soup(JUNK_TAGS):
        tag.decompose()
    for sel in JUNK_CONTAINER_SELECTORS:
        try:
            for el in soup.select(sel):
                if el.name in protected:
                    continue
                el.decompose()
        except Exception:
            continue
    return soup


# --- Signatures ---

def _text_bucket(n: int) -> int:
    for i, edge in enumerate((15, 40, 100, 250, 600)):
        if n < edge:
            return i
    return 5


def _signature(el: Tag, cache: dict) -> tuple:
    key = id(el)
    if key in cache:
        return cache[key]
    tags: Counter = Counter()

    def walk(node: Tag, depth: int):
        for ch in node.children:
            if isinstance(ch, Tag):
                tags[ch.name] += 1
                if depth < SIG_DEPTH_CAP:
                    walk(ch, depth + 1)

    walk(el, 1)
    sig = (el.name, tags, _text_bucket(len(el.get_text(strip=True))))
    cache[key] = sig
    return sig


def _similar(a: tuple, b: tuple) -> bool:
    if a[0] != b[0]:
        return False
    if abs(a[2] - b[2]) > 1:
        return False
    ta, tb = a[1], b[1]
    total = sum(ta.values()) + sum(tb.values())
    if total == 0:
        return True
    shared = sum(min(ta[k], tb[k]) for k in ta.keys() & tb.keys())
    return (2 * shared / total) >= SIG_SIMILARITY


# --- Record-density signals ---

def _has_contact_signal(el: Tag) -> bool:
    text = el.get_text(" ", strip=True)
    if _PHONE_RE.search(text) or _EMAIL_RE.search(text) or _ADDRESS_RE.search(text):
        return True
    for a in el.find_all("a", href=True):
        href = a["href"]
        if href.startswith("tel:") or href.startswith("mailto:"):
            return True
    return False


def _detail_templates(el: Tag) -> set[str]:
    """URL templates of links that plausibly lead to a record's own detail
    page: numeric id, uuid, or slug-like (hyphen/underscore) trailing path segment
    — the same shapes detail_crawler.detect_detail_links templatizes on.
    Returned as templates (varying part replaced) so the run scorer can
    require ONE SHARED template across the run: every real listing links
    /dentists/{slug} from every card, while a footer link column links a
    different section from every column."""
    templates: set[str] = set()
    for a in el.find_all("a", href=True):
        href = a["href"].split("#")[0]
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        path, _, query = href.partition("?")
        if _UUID_RE.search(href):
            templates.add(_UUID_RE.sub("{ID}", path))
            continue
        if re.search(r'\d{3,}', query):
            templates.add(path + "?" + re.sub(r'\d{3,}', "{ID}", query))
            continue
        head, _, last = path.rstrip("/").rpartition("/")
        if re.search(r'\d{3,}', last):
            templates.add(head + "/" + re.sub(r'\d{3,}', "{ID}", last))
        elif ("-" in last or "_" in last) and len(last) >= 4:
            templates.add(head + "/{SLUG}")
    return templates


def _anchor_dominated(el: Tag) -> bool:
    """True when essentially all of the node's text lives inside links —
    the shape of nav lists, dropdown option lists, and link-hub grids.
    (enigma's 693 a.dropdown-option and 401 hyphenated-slug industry links
    both pass the detail-link shape test; this is what keeps them out.)"""
    if el.name == "a":
        return True
    total = len(el.get_text("", strip=True))
    if total == 0:
        return True
    in_anchors = sum(len(a.get_text("", strip=True)) for a in el.find_all("a"))
    return (in_anchors / total) >= ANCHOR_DOMINANCE


def _structured_anchor(el: Tag) -> bool:
    """Whole-card anchor pattern: the node's text lives inside a link, but
    the link wraps a real card (heading + fields), not a flat label. Berkeley
    rosters wrap image+h2+titles in one <a>; enigma's <a>AK</a> dropdown
    options and flat industry link lists have no such structure."""
    anchors = [el] if el.name == "a" else el.find_all("a")
    for a in anchors:
        if a.find(["h1", "h2", "h3", "h4", "h5", "h6"]):
            return True
        texty = sum(1 for c in a.find_all(True) if c.get_text(strip=True))
        if texty >= 2:
            return True
    return False




def _is_separator(el: Tag) -> bool:
    if el.name in _SEPARATOR_TAGS:
        return True
    return not el.get_text(strip=True) and not el.find(True)


# --- Run discovery ---

def _find_runs(soup: BeautifulSoup) -> list[list[Tag]]:
    """All maximal runs of >=MIN_RUN near-identical adjacent element
    siblings, page-wide. Separator elements interleave without breaking a
    run (clearfix divs between cards) and are not counted."""
    sig_cache: dict = {}
    runs: list[list[Tag]] = []
    for parent in soup.find_all(True):
        children = [c for c in parent.children if isinstance(c, Tag)]
        if len(children) < MIN_RUN:
            continue
        run: list[Tag] = []
        for child in children:
            if run and _is_separator(child):
                continue
            if run and (
                _similar(_signature(child, sig_cache), _signature(run[0], sig_cache))
                or _similar(_signature(child, sig_cache), _signature(run[-1], sig_cache))
            ):
                run.append(child)
                continue
            if len(run) >= MIN_RUN:
                runs.append(run)
            run = [child] if not _is_separator(child) else []
        if len(run) >= MIN_RUN:
            runs.append(run)
    return runs


def _score_run(run: list[Tag]) -> float | None:
    """Record-density score; None = hard-rejected (not member records).

    A node counts as record-shaped when it has a contact signal, OR it
    carries a detail link matching the run's MAJORITY template (and isn't a
    bare link list). The shared-template requirement is what separates a
    roster whose every card links /people/{slug} from a footer of link
    columns where every column links somewhere different."""
    texts = [len(el.get_text(strip=True)) for el in run]
    med_text = median(texts)
    if med_text < MIN_MEDIAN_TEXT:
        return None

    contact = [_has_contact_signal(el) for el in run]
    tmpl_sets = [set() if has_c else _detail_templates(el)
                 for el, has_c in zip(run, contact)]
    tmpl_counts: Counter = Counter()
    for tmpls in tmpl_sets:
        tmpl_counts.update(tmpls)
    top_template = tmpl_counts.most_common(1)[0][0] if tmpl_counts else None

    shaped = 0
    for el, has_c, tmpls in zip(run, contact, tmpl_sets):
        if has_c:
            shaped += 1
        elif top_template in tmpls and (
            not _anchor_dominated(el) or _structured_anchor(el)
        ):
            shaped += 1
    density = shaped / len(run)
    if density < MIN_SIGNAL_DENSITY:
        return None
    return len(run) * (1 + 2 * density) + min(med_text / 10, 40)


# --- Wrapper descent ---

def _has_card_hint(el: Tag) -> bool:
    classes = " ".join(el.get("class") or []).lower()
    return any(h in classes for h in CARD_CLASS_HINTS)


def _descend_wrappers(run: list[Tag]) -> tuple[list[Tag], list[str]]:
    """When every run node is a 1:1 layout wrapper around the real card
    (GrowthZone's div.gz-list-col around div.gz-directory-card, Drupal's
    classless views rows), step down to the card. Count is unchanged —
    this only makes the emitted selector and samples point at the card.
    Never descends OUT of a node whose own class already marks it a card
    (fsConstituentItem must stay the record node).

    Also returns the tags stepped through: descended nodes no longer share
    a parent, so container-anchored selectors must route from the ORIGINAL
    run container through these wrapper hops."""
    hops: list[str] = []
    for _ in range(3):
        if _has_card_hint(run[0]):
            break
        children = []
        for el in run:
            kids = [c for c in el.children if isinstance(c, Tag) and not _is_separator(c)]
            if len(kids) != 1:
                return run, hops
            children.append(kids[0])
        if len({c.name for c in children}) != 1:
            return run, hops
        hops.append(run[0].name)
        run = children
    return run, hops


# --- Selector emission ---

def _shared_classes(run: list[Tag], allow_unstable: bool) -> list[str]:
    """Classes present on >=95% of run nodes, best candidate first. Fully
    deterministic order (hinted > longer > alphabetical) — set/dict
    iteration order must never decide which selector gets emitted."""
    counts: Counter = Counter()
    for el in run:
        for cls in set(el.get("class") or []):
            counts[cls] += 1
    usable = [
        cls for cls, n in counts.items()
        if n >= len(run) * 0.95
        and _CSS_IDENT_RE.match(cls)
        and cls.lower() not in _ZEBRA
        and cls.lower() not in LAYOUT_CLASS_EXACT
        and (allow_unstable or not _UNSTABLE_CLASS_RE.match(cls))
    ]
    # Card-hinted classes ("gz-directory-card") beat generic ones ("node"):
    # both would validate on THIS page, but the hinted one survives page
    # mutations and cache reuse far better. Validation downstream discards
    # any that over-match, so order is preference, not correctness.
    usable.sort(key=lambda c: (
        not any(h in c.lower() for h in CARD_CLASS_HINTS), -len(c), c))
    return usable


def _container_selector(container: Tag, allow_unstable: bool) -> str | None:
    """id > usable class > one anchored hop up. Kept short: the selector is
    consumed by querySelectorAll on the live page and cached, so shorter and
    more semantic wins over a brittle deep path."""
    parts: list[str] = []
    node = container
    for _ in range(3):
        if node is None or not isinstance(node, Tag) or node.name in ("html", "[document]"):
            break
        el_id = node.get("id")
        if el_id and _CSS_IDENT_RE.match(el_id) and (
            allow_unstable or not _UNSTABLE_CLASS_RE.match(el_id)
        ):
            parts.append(f"#{el_id}")
            return " > ".join(reversed(parts))
        classes = _shared_classes([node], allow_unstable)
        if classes:
            parts.append(f"{node.name}.{classes[0]}")
            return " > ".join(reversed(parts))
        if node.name == "body":
            parts.append("body")
            return " > ".join(reversed(parts))
        parts.append(node.name)
        node = node.parent
    return None


def _positional_path(container: Tag) -> str | None:
    """Last-resort emission for fully classless markup: an nth-of-type chain
    from <body> down to the container. Ugly but browser-valid; layout drift
    invalidates it, which the <3-live-matches re-derive rule absorbs."""
    parts: list[str] = []
    node = container
    for _ in range(12):
        if node is None or not isinstance(node, Tag):
            return None
        if node.name == "body":
            parts.append("body")
            return " > ".join(reversed(parts))
        parent = node.parent
        if not isinstance(parent, Tag):
            return None
        same_tag = [c for c in parent.children
                    if isinstance(c, Tag) and c.name == node.name]
        if len(same_tag) == 1:
            parts.append(node.name)
        else:
            parts.append(f"{node.name}:nth-of-type({same_tag.index(node) + 1})")
        node = parent
    return None


def _validate(selector: str, soup: BeautifulSoup, expected: int) -> int | None:
    """Round-trip the selector; return the guarded count (>=15 chars text,
    same floor the live JS counter applies) when it lands within
    [0.9x, ROUND_TRIP_SLACKx] of the run size, else None."""
    try:
        matched = soup.select(selector)
    except Exception:
        return None
    count = sum(1 for el in matched if len(el.get_text(strip=True)) >= MIN_MEDIAN_TEXT)
    if expected * 0.9 <= count <= expected * ROUND_TRIP_SLACK:
        return count
    return None


def _emit_selector(run: list[Tag], soup: BeautifulSoup,
                   full_soup: BeautifulSoup | None,
                   container: Tag | None = None,
                   hops: list[str] | None = None) -> tuple[str | None, int]:
    """Stable shared class > container-anchored path > unstable class >
    positional path. Each candidate must round-trip on the stripped soup
    AND (when given) the full unstripped soup — a selector that balloons
    once nav/footer are back in the tree would re-inflate the live count.

    container/hops describe wrapper descent: container is the PRE-descent
    run's parent and hops the wrapper tags stepped through (descended
    nodes no longer share a parent, so anchored paths route through them).
    """
    tag = run[0].name
    expected = len(run)
    hop_suffix = "".join(f" > {h}" for h in (hops or []))
    if container is None:
        container = run[0].parent if isinstance(run[0].parent, Tag) else None
    candidates: list[str] = []

    stable = _shared_classes(run, allow_unstable=False)
    candidates.extend(f"{tag}.{cls}" for cls in stable[:4])

    for allow_unstable in (False, True):
        if isinstance(container, Tag):
            csel = _container_selector(container, allow_unstable)
            if csel:
                candidates.append(f"{csel}{hop_suffix} > {tag}")

    unstable = _shared_classes(run, allow_unstable=True)
    candidates.extend(
        f"{tag}.{cls}" for cls in unstable[:4] if cls not in stable[:4]
    )

    if isinstance(container, Tag):
        ppath = _positional_path(container)
        if ppath:
            candidates.append(f"{ppath}{hop_suffix} > {tag}")

    seen: set[str] = set()
    for sel in candidates:
        if sel in seen:
            continue
        seen.add(sel)
        count = _validate(sel, soup, expected)
        if count is None:
            continue
        if full_soup is not None:
            count = _validate(sel, full_soup, expected)
            if count is None:
                continue
        return sel, count
    return None, 0


# --- Public API ---

def find_repeated_records_in_soup(
    soup: BeautifulSoup,
    full_soup: BeautifulSoup | None = None,
) -> tuple[str | None, int, list]:
    """Detect the member-record run in an already junk-stripped soup.

    Args:
        soup: junk-stripped tree (html_parser.extract_sample_html already
              holds one — this entry point avoids a double parse there).
        full_soup: optional UNSTRIPPED parse of the same page; when given,
              emitted selectors must also round-trip there, and the
              returned count is measured against it (that is what the
              live DOM will contain).

    Returns (selector, count, sample_nodes) or (None, 0, []).
    """
    runs = [(score, run) for run in _find_runs(soup)
            if (score := _score_run(run)) is not None]
    runs.sort(key=lambda x: x[0], reverse=True)

    for _score, run in runs[:5]:
        container = run[0].parent if isinstance(run[0].parent, Tag) else None
        run, hops = _descend_wrappers(run)
        selector, count = _emit_selector(run, soup, full_soup,
                                         container=container, hops=hops)
        if selector:
            return selector, count, run[:6]
    return None, 0, []


def find_repeated_records(html: str) -> tuple[str | None, int, list]:
    """Public entry: parse, strip junk, detect. Two parses on purpose —
    strip_junk mutates, and validation needs the intact tree (the live page
    the selector will run against still has its nav and footer)."""
    if not html:
        return None, 0, []
    full_soup = BeautifulSoup(html, "html.parser")
    stripped = _strip_junk(BeautifulSoup(html, "html.parser"))
    sel, count, samples = find_repeated_records_in_soup(stripped, full_soup=full_soup)
    if sel:
        return sel, count, samples
    # Fully classless markup: a positional (nth-of-type) path computed on
    # the stripped tree can't survive full-tree validation — stripping nav
    # siblings shifts the indexes. Retry on the intact tree; the record-
    # density gate alone keeps nav/menu runs out (the negative fixtures
    # pass without stripping too).
    return find_repeated_records_in_soup(full_soup)
