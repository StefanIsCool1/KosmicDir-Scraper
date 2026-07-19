"""Tests for the path-based-pager allowance in the pagination
navigated-away guard (browser._is_pagination_child).

Real-world shape: minnetonkamn.gov (CivicPlus) paginates its staff
directory via page-numbered CHILD paths (/staff-directory/-npage-2).
The guard's parent-anchored depth check treated those as navigating
away, went back, and stopped pagination after page 1 (20 of 128).
Deterministic — pure path logic, no network or browser.
"""

from browser import _is_pagination_child, _pick_path_pager

LISTING = "/government/contact-us/staff-directory"


# --- page-numbered children are pagination, not navigation away ---

def test_npage_child_allowed():
    assert _is_pagination_child(LISTING, LISTING + "/-npage-2")


def test_npage_last_page_allowed():
    assert _is_pagination_child(LISTING, LISTING + "/-npage-7")


def test_plain_page_dash_n():
    assert _is_pagination_child("/Minnesota", "/Minnesota/page-2")


def test_page_with_html_extension():
    assert _is_pagination_child("/Minnesota", "/Minnesota/page-2.html")


def test_page_as_own_segment():
    assert _is_pagination_child("/members", "/members/page/3")


def test_pg_prefix():
    assert _is_pagination_child("/members", "/members/pg2")


# --- non-pager children still count as navigated away ---

def test_alpha_filter_child_blocked():
    # minnetonkamn.gov's A–Z filter links live at the same depth as the
    # pager; they are not pagination and a click there should still be
    # undone by the guard.
    assert not _is_pagination_child(LISTING, LISTING + "/-alpha-A")


def test_detail_slug_child_blocked():
    assert not _is_pagination_child(LISTING, LISTING + "/john-smith")


def test_numeric_detail_id_blocked():
    # A bare-numeric child is ambiguous (could be a member id) — the
    # allowance requires an explicit page marker.
    assert not _is_pagination_child(LISTING, LISTING + "/1234")


def test_digits_inside_slug_blocked():
    assert not _is_pagination_child(LISTING, LISTING + "/suite-200-office")


def test_deeper_detail_path_blocked():
    assert not _is_pagination_child(
        "/member-directory/Find", "/member-directory/Details/company-123")


# --- non-children never match ---

def test_same_path_not_a_child():
    assert not _is_pagination_child(LISTING, LISTING)


def test_sibling_path_not_a_child():
    assert not _is_pagination_child(
        "/member-directory/Find", "/member-directory/search")


def test_empty_start_path():
    assert not _is_pagination_child("", "/anything/-npage-2")


# --- Phase 3: the path-segment pager FAST PATH (_pick_path_pager) --------
# _is_pagination_child only allows a click-pager child through the guard;
# _pick_path_pager builds a goto() template from the page-2/3 links so the
# walk skips clicking entirely (the /page/N/ exit criterion).

CIVIC = "https://city.gov/government/contact-us/staff-directory"


def test_path_pager_civicplus_child():
    got = _pick_path_pager(CIVIC, [
        ("/government/contact-us/staff-directory/-npage-2", "2"),
        ("/government/contact-us/staff-directory/-npage-3", "3"),
        ("/government/contact-us/staff-directory/john-smith", "John Smith"),
    ])
    assert got is not None
    prefix, suffix, last = got
    assert prefix + "2" + suffix == CIVIC + "/-npage-2"
    assert last == 3


def test_path_pager_page_n_slash():
    got = _pick_path_pager("https://s.com/members",
                           ["/members/page/2", "/members/page/3", "/members/page/4"])
    assert got and got[0] + "2" + got[1] == "https://s.com/members/page/2"
    assert got[2] == 4


def test_path_pager_sibling_replacement():
    # /blog/page/1 → /blog/page/2 (same depth, trailing number changes).
    got = _pick_path_pager("https://s.com/blog/page/1",
                           ["/blog/page/2", "/blog/page/3"])
    assert got and got[2] == 3


def test_path_pager_ignores_unrelated_sidebar_pager():
    # A /news/page/N pager elsewhere on the page must not be chosen as the
    # /directory listing's pager.
    assert _pick_path_pager("https://s.com/directory",
                            ["/news/page/2", "/news/page/3"]) is None


def test_path_pager_ignores_detail_slugs_with_digits():
    assert _pick_path_pager("https://s.com/directory", [
        "/directory/john-smith-123", "/directory/suite-200-office",
    ]) is None


def test_path_pager_declines_query_param_pager():
    # ?page=N is Strategy 0a's job — the path pager must return None so the
    # query-param walker isn't shadowed.
    assert _pick_path_pager("https://s.com/dir",
                            ["/dir?page=2", "/dir?page=3"]) is None


def test_path_pager_needs_two_distinct_pages():
    # A lone /page/2 link (no page 3+) isn't enough signal — mirrors the
    # query-param detector's len>=2 requirement.
    assert _pick_path_pager("https://s.com/members", ["/members/page/2"]) is None
