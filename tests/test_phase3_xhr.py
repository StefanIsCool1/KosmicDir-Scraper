"""Phase 3 (UNIVERSALITY_PLAN) — XHR replay universality, pagination
shapes, and the non-negotiable credential exclusion.

All offline: a fake page.context.request serves a synthetic directory, so
replay_directory_xhrs runs with no network/browser/LLM. Covers each Phase 3
exit criterion plus the credential-exclusion requirement (capture-time gate,
dump-time scrub, and end-to-end proof through main._finish_scrape).
"""

import json
import os
import tempfile
from urllib.parse import urlparse, parse_qs

import pytest

import browser as b
import config
import archetype
import main


# --- Synthetic directory server ---------------------------------------

def _members(start: int, size: int) -> list:
    """A page of `size` distinct member-shaped dicts (name+email+phone+
    company+address → passes both _is_directory_json and
    _looks_like_member_records)."""
    return [{
        "name": f"Member {i}",
        "email": f"m{i}@example.com",
        "phone": f"555-000-{i:04d}",
        "company": f"Company {i}",
        "address": f"{i} Main St",
    } for i in range(start, start + size)]


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeRequest:
    """Serves paginated / POST / cursor member data and records every call.

    total_pages pages of page_size members each, page N (1-indexed) →
    members [(N-1)*size .. N*size). Requests beyond total_pages return []."""

    def __init__(self, total_pages=5, page_size=20, page_param="page"):
        self.total_pages = total_pages
        self.page_size = page_size
        self.page_param = page_param
        self.get_calls = []
        self.post_calls = []

    def _page_payload(self, n: int):
        if n < 1 or n > self.total_pages:
            return []
        return _members((n - 1) * self.page_size, self.page_size)

    def get(self, url, timeout=None):
        self.get_calls.append(url)
        qs = parse_qs(urlparse(url).query, keep_blank_values=True)
        # cursor-token style (?pageToken=pN) or numeric page (?page=N)
        if "pageToken" in qs and qs["pageToken"][0]:
            n = int(qs["pageToken"][0].lstrip("p"))
            payload = {"items": self._page_payload(n)}
            if n < self.total_pages:
                payload["nextPageToken"] = f"p{n + 1}"
            return FakeResponse(payload)
        if "after" in qs and qs["after"][0]:
            n = int(qs["after"][0])
            payload = {"members": self._page_payload(n)}
            if n < self.total_pages:
                payload["paging"] = {"next": f"https://dir.example.com/api?after={n + 1}"}
            return FakeResponse(payload)
        n = int((qs.get(self.page_param, ["1"])[0] or "1"))
        return FakeResponse(self._page_payload(n))

    def post(self, url, data=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        body = data or ""
        try:
            obj = json.loads(body)
            n = int(obj.get("page", 1))
        except (json.JSONDecodeError, ValueError):
            qs = parse_qs(body, keep_blank_values=True)
            n = int((qs.get("page", ["1"])[0] or "1"))
        return FakeResponse(self._page_payload(n))


class FakeContext:
    def __init__(self, request):
        self.request = request


class FakePage:
    def __init__(self, request):
        self.context = FakeContext(request)


@pytest.fixture(autouse=True)
def _reset_archetype():
    archetype.reset()
    yield
    archetype.reset()


# --- Exit criterion: Playground (intent=None) pagination replay --------

def test_playground_pagination_ungated():
    """intent=None still walks a captured page/offset endpoint — the Phase 3
    relaxation of the Playground invariant (pagination mechanism only)."""
    req = FakeRequest(total_pages=5, page_size=20)
    page = FakePage(req)
    results = [{"url": "https://dir.example.com/api?page=1", "data": _members(0, 20)}]
    added = b.replay_directory_xhrs(page, results, intent=None)
    assert added == 80                      # pages 2..5
    assert b._count_json_member_records(results) == 100
    # pages 2..6 fetched (6 → [] ends it)
    assert any("page=2" in u for u in req.get_calls)
    assert any("page=6" in u for u in req.get_calls)


def test_flag_off_reverts_to_intent_gated(monkeypatch):
    """With PHASE3_XHR_PAGINATION off, intent=None replay is a no-op again
    (Phase 2 behavior) — the kill switch works without a code revert."""
    monkeypatch.setattr(b, "PHASE3_XHR_PAGINATION", False)
    req = FakeRequest(total_pages=5, page_size=20)
    page = FakePage(req)
    results = [{"url": "https://dir.example.com/api?page=1", "data": _members(0, 20)}]
    added = b.replay_directory_xhrs(page, results, intent=None)
    assert added == 0
    assert req.get_calls == []


# --- Exit criterion: 2,000-record aggregator exceeds the old 300 cap ---

def test_expected_aware_cap_exceeds_300():
    req = FakeRequest(total_pages=100, page_size=20)     # 2,000 members
    page = FakePage(req)
    results = [{"url": "https://dir.example.com/api?page=1", "data": _members(0, 20)}]
    # Site stated a total → caps stretch to 2000 * 1.2.
    archetype.note_expected_count(object(), {"type": "number", "count": 2000})
    b.replay_directory_xhrs(page, results, intent=None)
    total = b._count_json_member_records(results)
    assert total > 300, f"expected-aware cap should exceed 300, got {total}"
    assert total == 2000                     # full walk, natural end at page 100


def test_default_cap_limits_records():
    """No stated total → the fixed 300-record cap still holds (a runaway
    guard, not removed)."""
    req = FakeRequest(total_pages=100, page_size=20)
    page = FakePage(req)
    results = [{"url": "https://dir.example.com/api?page=1", "data": _members(0, 20)}]
    b.replay_directory_xhrs(page, results, intent=None)
    total = b._count_json_member_records(results)
    assert 300 <= total <= 340, total        # stops at the 300 ceiling
    assert total < 2000


# --- Exit criterion: POST-paginated fixture replays on Playground path --

def test_post_body_pagination():
    req = FakeRequest(total_pages=4, page_size=20)
    page = FakePage(req)
    results = [{
        "url": "https://dir.example.com/api/search",
        "method": "POST",
        "post_data": '{"page": 1, "size": 20}',
        "req_content_type": "application/json",
        "data": _members(0, 20),
    }]
    added = b.replay_directory_xhrs(page, results, intent=None)
    assert added == 60                       # pages 2..4
    assert b._count_json_member_records(results) == 80
    # the page field in the POST body was mutated, not the URL
    bodies = [json.loads(c["data"]) for c in req.post_calls]
    assert {bd["page"] for bd in bodies} >= {2, 3, 4}
    assert all(c["url"] == "https://dir.example.com/api/search" for c in req.post_calls)


def test_form_encoded_post_pagination():
    req = FakeRequest(total_pages=3, page_size=20)
    page = FakePage(req)
    results = [{
        "url": "https://dir.example.com/list",
        "method": "POST",
        "post_data": "page=1&q=all",
        "req_content_type": "application/x-www-form-urlencoded",
        "data": _members(0, 20),
    }]
    added = b.replay_directory_xhrs(page, results, intent=None)
    assert added == 40                       # pages 2..3
    assert any("page=2" in c["data"] for c in req.post_calls)


# --- Cursor / continuation-token pagination ---------------------------

def test_cursor_url_chain_followed():
    """paging.next full-URL chain (Facebook Graph shape)."""
    req = FakeRequest(total_pages=5, page_size=20)
    page = FakePage(req)
    seed = {"members": _members(0, 20),
            "paging": {"next": "https://dir.example.com/api?after=2"}}
    results = [{"url": "https://dir.example.com/api?after=1", "data": seed}]
    b.replay_directory_xhrs(page, results, intent=None)
    assert b._count_json_member_records(results) == 100      # 5 pages
    assert any("after=5" in u for u in req.get_calls)


def test_cursor_token_chain_followed():
    """Opaque nextPageToken → request param pageToken (Google list shape)."""
    req = FakeRequest(total_pages=4, page_size=20)
    page = FakePage(req)
    seed = {"items": _members(0, 20), "nextPageToken": "p2"}
    results = [{"url": "https://dir.example.com/api?pageToken=&q=x", "data": seed}]
    b.replay_directory_xhrs(page, results, intent=None)
    assert b._count_json_member_records(results) == 80       # 4 pages
    assert any("pageToken=p4" in u for u in req.get_calls)


# --- Term/letter mutation stays intent-gated --------------------------

def test_term_mutation_still_intent_gated():
    """A term-only endpoint (no page/cursor) yields nothing without intent —
    the universal relaxation is pagination ONLY, not intent-term search."""
    req = FakeRequest(total_pages=5, page_size=20)
    page = FakePage(req)
    results = [{"url": "https://dir.example.com/api?q=", "data": _members(0, 20)}]
    added = b.replay_directory_xhrs(page, results, intent=None)
    assert added == 0
    assert req.get_calls == []               # no candidate → no requests


def test_term_mutation_runs_with_intent():
    req = FakeRequest(total_pages=5, page_size=20)
    page = FakePage(req)
    # multi-char current value → q stays a TERM param (a single char would
    # be reclassified letter-like for starts-with engines).
    results = [{"url": "https://dir.example.com/api?q=all", "data": _members(0, 20)}]
    intent = {"industry_canonical": "dentists", "industry_aliases": ["dental"]}
    b.replay_directory_xhrs(page, results, intent=intent)
    assert any("q=dentists" in u for u in req.get_calls)


# --- CREDENTIAL EXCLUSION (non-negotiable) ----------------------------

def test_login_post_refused_at_capture():
    """_admit_json_capture refuses an auth-shaped request even when its
    response is member-shaped (a login returning a profile)."""
    results = []
    member_shaped = _members(0, 3)
    admitted = b._admit_json_capture(
        results, "https://site.com/api/auth/login", member_shaped,
        method="POST", post_data="username=admin&password=hunter2",
        req_content_type="application/x-www-form-urlencoded")
    assert admitted is False
    assert results == []


def test_credential_body_refused_even_on_neutral_url():
    results = []
    assert not b._admit_json_capture(
        results, "https://site.com/api/members", _members(0, 3),
        method="POST", post_data='{"q":"all","password":"hunter2"}',
        req_content_type="application/json")
    assert results == []


def test_csrf_token_not_refused():
    """CSRF/verification tokens ride legitimate POST search forms and must
    NOT be excluded, or POST replay dies on the sites it exists for."""
    results = []
    assert b._admit_json_capture(
        results, "https://site.com/api/search", _members(0, 3),
        method="POST", post_data="__RequestVerificationToken=abc&q=all&page=1",
        req_content_type="application/x-www-form-urlencoded")
    assert len(results) == 1


def test_sanitize_scrubs_login_from_dump():
    dirty = [
        {"url": "https://site.com/api/dir?page=1", "data": _members(0, 3)},
        {"url": "https://site.com/login", "method": "POST",
         "post_data": "user=a&password=hunter2", "data": {"ok": True}},
        {"url": "https://site.com/oauth/token", "method": "POST",
         "post_data": "grant_type=password&password=x", "data": {"access_token": "t"}},
    ]
    clean = b.sanitize_results_for_dump(dirty)
    assert len(clean) == 1
    assert clean[0]["url"].endswith("/api/dir?page=1")
    blob = json.dumps(clean)
    assert "hunter2" not in blob and "access_token" not in blob


def test_login_post_not_persisted_by_finish_scrape():
    """End-to-end proof: a login POST present in `results` never reaches the
    Data-dump/ raw file written by main._finish_scrape."""
    archetype.reset()
    with tempfile.TemporaryDirectory() as tmp:
        domain = "testsite_com"
        results = [
            {"url": "https://testsite.com/api/directory?page=1",
             "data": [{"name": "GoodCorp", "company_name": "GoodCorp",
                       "email": "hi@goodcorp.com", "phone": "555-1000",
                       "address": "1 Main"}]},
            {"url": "https://testsite.com/api/auth/login", "method": "POST",
             "post_data": "username=admin&password=hunter2",
             "req_content_type": "application/x-www-form-urlencoded",
             "data": {"success": True, "userId": 42}},
        ]
        main._finish_scrape(
            "https://testsite.com/", domain, tmp, results, detail_urls=[],
            prompt_callback=lambda *a, **k: False, priority_fields=[],
            intent=None, redrive_fn=None, crawl_all=False)

        raw_path = os.path.join(tmp, f"{domain}.json")
        assert os.path.exists(raw_path)
        raw_text = open(raw_path).read()
        assert "hunter2" not in raw_text, "password persisted to raw dump"
        assert "password" not in raw_text
        assert "/auth/login" not in raw_text
        # legit directory data is still there
        assert "GoodCorp" in raw_text


# --- Pure-helper regression (POST body / cursor / path pager) ----------

def test_body_enum_and_mutate_json():
    p = b._find_enumerable_body_params('{"pageNumber":1,"keyword":"x"}',
                                       "application/json")
    assert p["page"] == ["pageNumber"]
    # JSON string page preserves string type; numeric stays numeric
    assert b._mutate_body('{"page":"1"}', "application/json", "page", 2) == '{"page": "2"}'
    assert b._mutate_body('{"page":1}', "application/json", "page", 2) == '{"page": 2}'


def test_body_enum_and_mutate_form():
    p = b._find_enumerable_body_params("page=1&q=all",
                                       "application/x-www-form-urlencoded")
    assert p["page"] == ["page"]
    assert b._mutate_body("page=1&q=all", None, "page", 2) == "page=2&q=all"


def test_find_continuation_shapes():
    assert b._find_continuation({"data": [1], "paging": {"next": "http://x/y"}}) \
        == ("next", "http://x/y")
    assert b._find_continuation({"nextPageToken": "TK", "items": [1]}) \
        == ("nextPageToken", "TK")
    assert b._find_continuation({"data": [1], "next": "0"}) is None      # end
    assert b._find_continuation({"data": [1], "hasNext": True}) is None  # bool


def test_cursor_request_param_maps_google_shape():
    assert b._cursor_request_param("nextPageToken",
                                   "https://x/api?q=1", None, None) == "pageToken"
    assert b._cursor_request_param("nextPageToken",
                                   "https://x/api?pageToken=&q=1", None, None) == "pageToken"
    assert b._cursor_request_param("next_cursor",
                                   "https://x/api?cursor=&q=1", None, None) == "cursor"
