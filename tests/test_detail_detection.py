"""Tests for detail-link detection and the crawl-all decision.

Real-world shape: minnetonkamn.gov (CivicPlus). Member detail links live
at /Home/Components/StaffDirectory/StaffDirectory/{memberId}/{pageId},
while the listing's chrome — 27 letter filters (/-alpha-A), 6 pager links
(/-npage-2), sort links (/-sortd-asc) — templatizes into its own group.
Chrome repeats on every captured page, so score-before-dedup picked the
chrome group (33 links) and threw the 128 real member links away.
Deterministic — no network, no LLM, no browser.
"""

import json
import string

from detail_crawler import detect_detail_links

BASE = "https://www.minnetonkamn.gov"
LISTING = BASE + "/government/contact-us/staff-directory"


def _link(href):
    return {"href": href, "inNav": False}


def _member_links(count, npage=None, start=300):
    """Member detail links as CivicPlus renders them: bare on page 1,
    tagged with the listing page they appeared on (?npage=N) after that."""
    suffix = f"?npage={npage}" if npage else ""
    return [
        _link(f"{BASE}/Home/Components/StaffDirectory/StaffDirectory/"
              f"{start + i}/3436{suffix}")
        for i in range(count)
    ]


def _chrome_links():
    """One page's worth of filter/pager/sort chrome."""
    alpha = [_link(f"{LISTING}/-alpha-{c}") for c in string.ascii_uppercase]
    alpha.append(_link(f"{LISTING}/-alpha-NonAlpha"))
    pager = [_link(f"{LISTING}/-npage-{n}") for n in range(2, 8)]
    sorts = [_link(f"{LISTING}/-sortn-SName/-sortd-asc#SName_1_2_3")]
    return alpha + pager + sorts


def test_member_links_beat_repeated_chrome():
    """7 paginated pages: each member link appears once (20 per page, 8 on
    the last, ?npage=N tagged after page 1), chrome repeats on every page.
    The member links must land in ONE group — the ?npage tag must not
    split them into per-page groups — and that group must win."""
    links = []
    for page in range(1, 8):
        count = 8 if page == 7 else 20
        links.extend(_member_links(count, npage=None if page == 1 else page,
                                   start=300 + (page - 1) * 20))
        links.extend(_chrome_links())
    detected = detect_detail_links(links)
    assert len(detected) == 128
    assert all("/Home/Components/StaffDirectory/" in u for u in detected)


def test_small_single_page_directory():
    """Fewer members than chrome links (18 vs 34) — raw counts would pick
    chrome even after dedup; the chrome exclusion must keep it out."""
    links = _member_links(18) + _chrome_links()
    detected = detect_detail_links(links)
    assert len(detected) == 18
    assert all("/Home/Components/StaffDirectory/" in u for u in detected)


def test_chrome_only_yields_nothing():
    links = []
    for _ in range(7):
        links.extend(_chrome_links())
    assert detect_detail_links(links) == []


def test_generic_page_slugs_excluded():
    """Non-CivicPlus page-numbered slugs (/page-2) are excluded too."""
    links = _member_links(10)
    links += [_link(f"{BASE}/some-directory/page-{n}") for n in range(2, 9)]
    detected = detect_detail_links(links)
    assert all("/page-" not in u for u in detected)
    assert len(detected) == 10


def test_query_id_pattern_still_detected():
    """Regression: the classic ?id=N template group still works."""
    links = [_link(f"https://example.org/members/?id=1000{i}") for i in range(6)]
    detected = detect_detail_links(links)
    assert len(detected) == 6


def test_bare_query_pager_not_a_detail_group():
    """A ?page=N pager carries no ID — page-param stripping alone must not
    qualify it as a detail template, even when it outnumbers the members."""
    links = [_link(f"https://example.org/directory?page={n}") for n in range(2, 40)]
    links += _member_links(10)
    detected = detect_detail_links(links)
    assert len(detected) == 10
    assert all("?page=" not in u for u in detected)


def test_slug_members_with_page_tags_group_together():
    """Slug-based detail links tagged with the listing page they appeared
    on must still hit the slug rule and unify into one group."""
    links = [
        _link(f"https://example.org/members/company-{i}-inc"
              f"{'' if page == 1 else f'?npage={page}'}")
        for page, i in [(1, 1), (1, 2), (2, 3), (2, 4), (3, 5), (3, 6)]
    ]
    detected = detect_detail_links(links)
    assert len(detected) == 6


# --- crawl-all wiring in main._finish_scrape ---

def _run_finish(tmp_path, monkeypatch, crawl_all):
    import main

    crawled = []

    def fake_crawl(urls, domain):
        crawled.extend(urls)
        return []

    monkeypatch.setattr(main, "parse_and_save_results",
                        lambda *a, **k: ([{"name": "A", "phone": "1"}], None))
    monkeypatch.setattr(main, "_check_fields_from_raw",
                        lambda results: {"email", "phone"})
    monkeypatch.setattr(main, "crawl_detail_pages", fake_crawl)

    detail_urls = ["https://x.test/dir/1", "https://x.test/dir/2",
                   "https://x.test/dir/3"]
    members = main._finish_scrape(
        "https://x.test/dir", "x_test", str(tmp_path),
        results=[], detail_urls=detail_urls,
        prompt_callback=lambda n, m=None: False,  # declines if ever asked
        priority_fields=["email", "phone"], intent=None,
        redrive_fn=None, crawl_all=crawl_all)
    return members, crawled, detail_urls


def test_crawl_all_forces_detail_crawl(tmp_path, monkeypatch):
    """crawl_all crawls every detail page even though all priority fields
    are already present (which normally skips the crawl)."""
    members, crawled, detail_urls = _run_finish(tmp_path, monkeypatch,
                                                crawl_all=True)
    assert crawled == detail_urls
    assert members


def test_without_crawl_all_satisfied_fields_skip(tmp_path, monkeypatch):
    """Control: same inputs without crawl_all — fields satisfied, no crawl."""
    members, crawled, _ = _run_finish(tmp_path, monkeypatch, crawl_all=False)
    assert crawled == []
    assert members
