"""Deterministic checks for the "person" entity-type path (rosters, faculty/
team pages). Exercises extraction → clean/dedup → garbage-gate → metadata →
cached parse without any LLM or browser calls, plus the mailto/boilerplate
fixes to the shared regex helpers and a business-regression check.
Run: python3 test_person_schema.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Bot"))

import html_parser  # noqa: E402
from html_parser import (  # noqa: E402
    apply_selectors, _selectors_valid, _extract_company_name,
    _strip_cms_boilerplate, parse_member_html, extract_sample_html,
    learn_selectors_from_table_headers, _parse_llm_json,
)
from cleaner import (  # noqa: E402
    clean_members, is_extraction_garbage_person, is_extraction_garbage,
)
from cache import (  # noqa: E402
    set_cached_selectors, get_cached_selectors, delete_cached_selectors,
)
from main import compute_metadata  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


# UC-Berkeley-style graduate student roster: Drupal table with zebra-striped
# rows (odd/even), a thead, mailto links, and "(link sends e-mail)" /
# "(link is external)" boilerplate.
PEOPLE_HTML = """
<table class="views-table">
 <thead><tr><th>Name</th><th>Preferred Pronouns</th><th>Email</th><th>Personal Website</th></tr></thead>
 <tbody>
  <tr class="odd"><td>Ahmad Abassi</td><td>He/Him</td>
      <td><a href="mailto:zaid_abassi@berkeley.edu">zaid_abassi@berkeley.edu</a>(link sends e-mail)</td>
      <td></td></tr>
  <tr class="even"><td>Raha Ahmadian</td><td></td>
      <td>raha.ahmadian@berkeley.edu(link sends e-mail)</td>
      <td></td></tr>
  <tr class="odd"><td>Joao Basso</td><td></td>
      <td><a href="mailto:joao.basso@berkeley.edu">joao.basso@berkeley.edu</a>(link sends e-mail)</td>
      <td><a href="https://joaomvbasso.github.io">https://joaomvbasso.github.io</a>(link is external)</td></tr>
  <tr class="even"><td>Katalin Berlow</td><td>She/Her</td>
      <td><a href="mailto:katalin@berkeley.edu">katalin@berkeley.edu</a>(link sends e-mail)</td>
      <td><a href="https://katalinberlow.github.io/">https://katalinberlow.github.io/</a>(link is external)</td></tr>
 </tbody>
</table>
"""

PERSON_SELECTORS = {
    "entity_type": "person",
    "card_selector": "table.views-table > tbody > tr",
    "name_field": "full_name",
    "full_name": "td:nth-of-type(1)",
    "pronouns": "td:nth-of-type(2)",
    "title": None,
    "department": None,
    "office": None,
    "email": "td:nth-of-type(3) a",
    "phone": None,
    "personal_website": "td:nth-of-type(4) a",
}


def test_person_extract_clean_metadata():
    recs = apply_selectors(PEOPLE_HTML, PERSON_SELECTORS)  # person dispatch
    assert len(recs) == 4, recs
    assert recs[0]["full_name"] == "Ahmad Abassi", recs[0]
    assert recs[0]["pronouns"] == "He/Him"
    assert recs[0]["email"] == "zaid_abassi@berkeley.edu"  # from mailto href
    assert recs[0]["personal_website"] is None
    # No selector match on the email cell (plain text, no <a>) → card fallback
    assert recs[1]["email"] == "raha.ahmadian@berkeley.edu", recs[1]
    assert recs[2]["personal_website"] == "https://joaomvbasso.github.io"
    # Boilerplate never leaks into any value
    for r in recs:
        for v in r.values():
            assert not (v and "link sends" in v), r
            assert not (v and "link is external" in v), r
    assert _selectors_valid(PERSON_SELECTORS, recs)

    cleaned = clean_members(recs, name_field="full_name", entity_type="person")
    assert len(cleaned) == 4, "no records should be dropped"
    assert cleaned[1]["pronouns"] is None  # empty cell → None
    assert not is_extraction_garbage_person(cleaned)

    md = compute_metadata(cleaned, source_url="http://x",
                          entity_type="person", name_field="full_name")
    assert md["entity_type"] == "person"
    assert md["name_field"] == "full_name"
    assert md["with_name"] == 4
    assert md["field_coverage"]["email"] == 4
    assert md["field_coverage"]["personal_website"] == 2
    print("  person extract/clean/metadata OK ->", cleaned[0])
    return cleaned


def test_person_dedup_and_drop():
    rows = [
        {"full_name": "John Smith", "email": "j.smith@x.edu"},
        {"full_name": "John Smith", "email": "j.smith@x.edu"},   # dup → removed
        {"full_name": "John Smith", "email": "john2@x.edu"},     # same name, diff email → kept
        {"full_name": "jane.doe@x.edu", "email": "jane.doe@x.edu"},  # email-as-name → dropped
        {"full_name": "Name", "email": "hdr@x.edu"},             # header label → dropped
        {"full_name": "", "email": "ghost@x.edu"},               # no identity → dropped
    ]
    cleaned = clean_members(rows, entity_type="person")
    names = [(m["full_name"], m["email"]) for m in cleaned]
    assert len(cleaned) == 2, names
    assert names == [("John Smith", "j.smith@x.edu"), ("John Smith", "john2@x.edu")], names
    print("  person dedup/drop OK ->", names)


def test_person_field_normalization():
    rows = [{
        "full_name": "  Ada   Lovelace ",
        "pronouns": "(She/Her)",
        "title": " Graduate  Student ",
        "email": "mailto:Ada@Berkeley.EDU?subject=hi",
        "phone": "5105551234",
        "personal_website": "adalovelace.github.io",
    }, {
        "full_name": "Bob",
        "email": "bob@x.edu(link sends e-mail)",   # boilerplate remnant → salvaged
        "pronouns": None,
        "phone": None,
        "personal_website": "mailto:bob@x.edu",     # model pointed site at mailto
    }]
    out = clean_members(rows, entity_type="person")
    a, b = out[0], out[1]
    assert a["full_name"] == "Ada Lovelace", a
    assert a["pronouns"] == "She/Her", a
    assert a["title"] == "Graduate Student", a
    assert a["email"] == "ada@berkeley.edu", a
    assert a["phone"] == "(510) 555-1234", a
    assert a["personal_website"] == "https://adalovelace.github.io", a
    assert b["email"] == "bob@x.edu", b
    assert b["personal_website"] is None, b
    print("  person field normalization OK ->", a)


def test_person_garbage_gate():
    names_only = [{"full_name": f"Person {i}", "email": None} for i in range(10)]
    assert is_extraction_garbage_person(names_only), "bare-name list must be garbage"
    with_data = [{"full_name": f"Person {i}", "email": f"p{i}@x.edu"} for i in range(10)]
    assert not is_extraction_garbage_person(with_data)
    print("  person garbage gate OK")


def test_extract_company_name_mailto_fix():
    # Card whose only link is a mailto — the email must NOT become the name
    soup = BeautifulSoup(
        '<tr><td>Raha Ahmadian</td>'
        '<td><a href="mailto:r@x.edu">r@x.edu</a>(link sends e-mail)</td></tr>',
        "html.parser")
    assert _extract_company_name(soup) is None, "mailto text must not leak in as name"

    # mailto first, real link second → real link text wins
    soup = BeautifulSoup(
        '<div><a href="mailto:info@acme.com">info@acme.com</a>'
        '<a href="https://acme.com">Acme Corp</a></div>', "html.parser")
    assert _extract_company_name(soup) == "Acme Corp"

    # Heading that is just an email → skipped in favor of the link
    soup = BeautifulSoup(
        '<div><h3>info@acme.com</h3><a href="/acme">Acme Corp</a></div>',
        "html.parser")
    assert _extract_company_name(soup) == "Acme Corp"

    # Boilerplate stripped from a legit heading
    soup = BeautifulSoup(
        '<div><h3>Acme Corp(link is external)</h3></div>', "html.parser")
    assert _extract_company_name(soup) == "Acme Corp"

    assert _strip_cms_boilerplate("Jane Doe(opens in a new tab)") == "Jane Doe"
    print("  _extract_company_name mailto/boilerplate fix OK")


def test_learn_selectors_person_branch():
    """learn_selectors must accept a person schema, stamp name_field, and cache
    it; a person schema without full_name must not be cached."""
    import json as _json
    domain = "person_learn_test_fake"
    good = dict(PERSON_SELECTORS)
    good.pop("name_field")  # the model doesn't return this — learn adds it

    real_ask = html_parser.ask
    try:
        html_parser.ask = lambda *a, **k: _json.dumps(good)
        sel = html_parser.learn_selectors(PEOPLE_HTML, domain)
        assert sel["entity_type"] == "person"
        assert sel["name_field"] == "full_name"
        from cache import get_cached_selectors
        assert get_cached_selectors(domain), "person schema should be cached"
        delete_cached_selectors(domain)

        bad = {k: v for k, v in good.items() if k != "full_name"}
        html_parser.ask = lambda *a, **k: _json.dumps(bad)
        sel = html_parser.learn_selectors(PEOPLE_HTML, domain)
        assert get_cached_selectors(domain) is None, "no full_name → must not cache"
    finally:
        html_parser.ask = real_ask
        delete_cached_selectors(domain)
    print("  learn_selectors person branch OK")


def test_cached_person_parse_end_to_end():
    """parse_member_html with a cached person schema: zero AI, full pipeline."""
    domain = "person_cached_test_fake"
    set_cached_selectors(domain, dict(PERSON_SELECTORS))
    try:
        members = parse_member_html(PEOPLE_HTML, domain=domain)
        assert len(members) == 4, members
        assert members[3]["full_name"] == "Katalin Berlow"
        assert members[3]["email"] == "katalin@berkeley.edu"
        assert members[3]["personal_website"] == "https://katalinberlow.github.io/"
    finally:
        delete_cached_selectors(domain)
    print("  cached person parse end-to-end OK ->", members[0])


def test_zebra_classes_not_grouped():
    """tr.odd must never win card detection — it covers only half the rows.
    The zebra skip pushes striped tables to parent-based sibling grouping."""
    _sample, selector = extract_sample_html(PEOPLE_HTML)
    assert selector and ".odd" not in selector and ".even" not in selector, selector
    soup = BeautifulSoup(PEOPLE_HTML, "html.parser")
    assert len(soup.select(selector)) == 4, f"'{selector}' must cover ALL rows"
    print(f"  zebra grouping OK -> '{selector}' covers odd AND even rows")


def test_header_table_learning():
    """Labeled tables map columns to fields deterministically — zero AI."""
    sel, confident = learn_selectors_from_table_headers(PEOPLE_HTML)
    assert sel, "Berkeley-style table must map"
    assert confident, "pronouns column → confidently person"
    assert sel["entity_type"] == "person"
    assert sel["name_field"] == "full_name"
    assert sel["full_name"] == "td:nth-of-type(1)", sel
    assert sel["pronouns"] == "td:nth-of-type(2)", sel
    assert sel["email"] == "td:nth-of-type(3)", sel
    assert sel["personal_website"] == "td:nth-of-type(4)", sel

    recs = apply_selectors(PEOPLE_HTML, sel)
    assert len(recs) == 4, recs
    assert recs[0]["full_name"] == "Ahmad Abassi"
    assert recs[0]["email"] == "zaid_abassi@berkeley.edu"
    assert recs[3]["personal_website"] == "https://katalinberlow.github.io/"

    # A plain page with no labeled table maps to nothing
    sel, _ = learn_selectors_from_table_headers("<div><p>hello</p></div>")
    assert sel == {}, sel
    print("  header-table learning OK ->", recs[0])


def test_parse_llm_json():
    assert _parse_llm_json('{"a": 1}') == {"a": 1}
    assert _parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_llm_json('Here is the JSON:\n{"a": 1}\nHope that helps!') == {"a": 1}
    assert _parse_llm_json("") is None
    assert _parse_llm_json("Sorry, I cannot do that.") is None
    assert _parse_llm_json('[1, 2]') is None  # not a dict
    print("  _parse_llm_json OK")


def test_llm_retry_on_empty():
    """One empty LLM response must not sink learning — retry once."""
    import json as _json
    domain = "person_retry_test_fake"
    good = dict(PERSON_SELECTORS)
    good.pop("name_field")
    calls = []

    def flaky_ask(*a, **k):
        calls.append(1)
        return "" if len(calls) == 1 else _json.dumps(good)

    real_ask = html_parser.ask
    try:
        html_parser.ask = flaky_ask
        sel = html_parser.learn_selectors(PEOPLE_HTML, domain)
        assert len(calls) == 2, calls
        assert sel.get("entity_type") == "person", sel
    finally:
        html_parser.ask = real_ask
        delete_cached_selectors(domain)
    print("  LLM retry-on-empty OK")


def test_confident_person_table_skips_llm():
    """A pronouns-labeled table extracts via header mapping with NO LLM call."""
    domain = "person_headertier_test_fake"

    def must_not_call(*a, **k):
        raise AssertionError("LLM must not be called for a confident person table")

    real_ask = html_parser.ask
    try:
        html_parser.ask = must_not_call
        members = parse_member_html(PEOPLE_HTML, domain=domain)
        assert len(members) == 4, members
        assert members[0]["full_name"] == "Ahmad Abassi"
        cached = get_cached_selectors(domain)
        assert cached and cached["entity_type"] == "person", cached
    finally:
        html_parser.ask = real_ask
        delete_cached_selectors(domain)
    print("  confident person table skips LLM OK")


def test_llm_down_header_fallback():
    """LLM permanently down + ambiguous headers ("Name|Email|Website", no
    pronouns): the header mapping still rescues the scrape at Step 2.5."""
    rows = "".join(
        f'<tr><td>Person {i}</td>'
        f'<td><a href="mailto:p{i}@x.edu">p{i}@x.edu</a></td>'
        f'<td><a href="https://p{i}.example.com">site</a></td></tr>'
        for i in range(6))
    html = ('<table id="staff"><thead><tr><th>Name</th><th>Email</th>'
            f'<th>Website</th></tr></thead><tbody>{rows}</tbody></table>')
    domain = "person_llmdown_test_fake"

    real_ask = html_parser.ask
    try:
        html_parser.ask = lambda *a, **k: ""  # LLM returns nothing, always
        members = parse_member_html(html, domain=domain)
        assert len(members) == 6, members
        assert members[0]["full_name"] == "Person 0"
        assert members[0]["email"] == "p0@x.edu"
        assert members[0]["personal_website"] == "https://p0.example.com"
        cached = get_cached_selectors(domain)
        assert cached and cached["entity_type"] == "person", cached
    finally:
        html_parser.ask = real_ask
        delete_cached_selectors(domain)
    print("  LLM-down header fallback OK")


def test_url_not_extracted_as_name():
    """A personal-website link's URL text must not become the name (this is
    what produced 27 URL-named 'members' on the Berkeley run)."""
    soup = BeautifulSoup(
        '<tr><td>Joao Basso</td>'
        '<td><a href="mailto:j@x.edu">j@x.edu</a></td>'
        '<td><a href="https://joao.github.io">https://joao.github.io</a></td></tr>',
        "html.parser")
    assert _extract_company_name(soup) is None
    print("  URL-as-name rejection OK")


def test_business_regression():
    card = ('<div class="m"><h3>Acme Corp</h3>'
            '<a href="http://acme.com">site</a>'
            '<span class="p">(206) 555-1234</span></div>')
    html = '<div class="list">' + card * 4 + '</div>'
    sel = {
        "card_selector": "div.m", "company_name": "h3", "website": "a", "phone": "span.p",
        "description": None, "category": None, "fax": None,
        "street_address": None, "mailing_address": None,
        "contact_card": None, "contact_name": None, "contact_email": None,
    }  # no entity_type → must use the unchanged business path
    recs = apply_selectors(html, sel)
    expected = {"company_name", "description", "category", "website", "phone",
                "fax", "street_address", "mailing_address", "contacts"}
    assert recs and set(recs[0].keys()) == expected, recs[0].keys()
    assert recs[0]["company_name"] == "Acme Corp"
    assert recs[0]["phone"] == "(206) 555-1234"

    cleaned = clean_members(recs)  # default business path
    assert cleaned[0]["company_name"] == "Acme Corp"
    assert not is_extraction_garbage(cleaned)

    # The one intended business-visible change: CMS boilerplate is stripped
    dirty = ('<div class="m"><h3>Acme Corp(link is external)</h3>'
             '<a href="http://acme.com">site</a>'
             '<span class="p">(206) 555-1234</span></div>')
    recs = apply_selectors('<div class="list">' + dirty * 4 + '</div>', sel)
    assert recs[0]["company_name"] == "Acme Corp", recs[0]
    print("  business regression OK -> unchanged 9-key shape, boilerplate stripped")


def test_csv_columns():
    try:
        from app import _records_to_csv
    except Exception as e:  # heavy deps may be unavailable outside the venv
        print(f"  CSV test skipped (could not import app: {str(e)[:60]})")
        return
    recs = apply_selectors(PEOPLE_HTML, PERSON_SELECTORS)
    csv_text = _records_to_csv(recs, entity_type="person")
    header = csv_text.splitlines()[0]
    for col in ("full_name", "pronouns", "email", "personal_website"):
        assert col in header, f"{col} missing from CSV header: {header}"
    print("  CSV person columns OK ->", header)


if __name__ == "__main__":
    print("test_person_extract_clean_metadata"); test_person_extract_clean_metadata()
    print("test_person_dedup_and_drop"); test_person_dedup_and_drop()
    print("test_person_field_normalization"); test_person_field_normalization()
    print("test_person_garbage_gate"); test_person_garbage_gate()
    print("test_extract_company_name_mailto_fix"); test_extract_company_name_mailto_fix()
    print("test_learn_selectors_person_branch"); test_learn_selectors_person_branch()
    print("test_cached_person_parse_end_to_end"); test_cached_person_parse_end_to_end()
    print("test_zebra_classes_not_grouped"); test_zebra_classes_not_grouped()
    print("test_header_table_learning"); test_header_table_learning()
    print("test_parse_llm_json"); test_parse_llm_json()
    print("test_llm_retry_on_empty"); test_llm_retry_on_empty()
    print("test_confident_person_table_skips_llm"); test_confident_person_table_skips_llm()
    print("test_llm_down_header_fallback"); test_llm_down_header_fallback()
    print("test_url_not_extracted_as_name"); test_url_not_extracted_as_name()
    print("test_business_regression"); test_business_regression()
    print("test_csv_columns"); test_csv_columns()
    print("\nALL PASS")
