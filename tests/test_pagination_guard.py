"""Tests for the path-based-pager allowance in the pagination
navigated-away guard (browser._is_pagination_child).

Real-world shape: minnetonkamn.gov (CivicPlus) paginates its staff
directory via page-numbered CHILD paths (/staff-directory/-npage-2).
The guard's parent-anchored depth check treated those as navigating
away, went back, and stopped pagination after page 1 (20 of 128).
Deterministic — pure path logic, no network or browser.
"""

from browser import _is_pagination_child

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
