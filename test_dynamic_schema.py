"""Deterministic checks for the dynamic (non-business) schema path.

Exercises extraction → clean/dedup → garbage-gate → metadata → CSV without any
LLM or browser calls, plus a business-regression check (the business path must
stay unchanged). Run: python3 test_dynamic_schema.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Bot"))

from html_parser import apply_selectors, _selectors_valid  # noqa: E402
from cleaner import (  # noqa: E402
    clean_members, is_extraction_garbage_dynamic, is_extraction_garbage,
)
from main import compute_metadata  # noqa: E402


GPU_HTML = """
<div class="gpu-list">
  <div class="gpu-card">
    <a class="name" href="/gpu/rtx-4090">GeForce RTX 4090</a>
    <span class="chipset">AD102</span><span class="mem">24 GB GDDR6X</span>
    <span class="tdp">450 W</span><span class="price">$1599</span>
  </div>
  <div class="gpu-card">
    <a class="name" href="/gpu/rx-7900">Radeon RX 7900 XTX</a>
    <span class="chipset">Navi 31</span><span class="mem">24 GB GDDR6</span>
    <span class="tdp">355 W</span><span class="price">$999</span>
  </div>
  <div class="gpu-card">
    <a class="name" href="/gpu/rtx-4080">GeForce RTX 4080</a>
    <span class="chipset">AD103</span><span class="mem">16 GB GDDR6X</span>
    <span class="tdp">320 W</span><span class="price">$1199</span>
  </div>
</div>
"""

GPU_SELECTORS = {
    "entity_type": "product",
    "card_selector": "div.gpu-card",
    "name_field": "model",
    "fields": [
        {"key": "model", "selector": "a.name", "role": "identity"},
        {"key": "chipset", "selector": "span.chipset", "role": "spec"},
        {"key": "memory", "selector": "span.mem", "role": "spec"},
        {"key": "tdp", "selector": "span.tdp", "role": "spec"},
        {"key": "price", "selector": "span.price", "role": "price"},
        {"key": "detail_url", "selector": "a.name", "role": "url"},
    ],
}
GPU_ROLES = {f["key"]: f["role"] for f in GPU_SELECTORS["fields"]}


def test_dynamic_extract_clean_metadata():
    recs = apply_selectors(GPU_HTML, GPU_SELECTORS)  # dispatches to dynamic path
    assert len(recs) == 3, recs
    assert recs[0]["model"] == "GeForce RTX 4090", recs[0]
    assert recs[0]["chipset"] == "AD102"
    assert recs[0]["detail_url"] == "/gpu/rtx-4090"  # url role → href, not text
    assert _selectors_valid(GPU_SELECTORS, recs)

    cleaned = clean_members(recs, name_field="model", is_dynamic=True, field_roles=GPU_ROLES)
    assert len(cleaned) == 3, "no records should be dropped"
    assert not is_extraction_garbage_dynamic(cleaned, "model")

    md = compute_metadata(cleaned, source_url="http://x",
                          entity_type="product", name_field="model")
    assert md["entity_type"] == "product"
    assert md["name_field"] == "model"
    assert md["with_name"] == 3
    assert md["field_coverage"]["chipset"] == 3
    assert md["field_coverage"]["price"] == 3
    print("  dynamic extract/clean/metadata OK ->", cleaned[0])
    return cleaned


def test_dynamic_dedup_and_drop():
    rows = [
        {"model": "RTX 4090", "chipset": "AD102"},
        {"model": "RTX 4090", "chipset": "AD102"},  # dup → removed
        {"model": "", "chipset": "x"},              # no identity → dropped
    ]
    cleaned = clean_members(rows, name_field="model", is_dynamic=True,
                            field_roles={"model": "identity", "chipset": "spec"})
    assert len(cleaned) == 1, cleaned
    print("  dynamic dedup/drop OK")


def test_role_normalization():
    rows = [{"name": "X", "tel": "2065551234", "site": "example.com", "mail": "A@B.COM "}]
    roles = {"name": "identity", "tel": "phone", "site": "url", "mail": "email"}
    out = clean_members(rows, name_field="name", is_dynamic=True, field_roles=roles)[0]
    assert out["tel"] == "(206) 555-1234", out
    assert out["site"] == "https://example.com", out
    assert out["mail"] == "a@b.com", out
    print("  role normalization OK ->", out)


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

    cleaned = clean_members(recs)  # default business path
    assert cleaned[0]["company_name"] == "Acme Corp"
    assert not is_extraction_garbage(cleaned)

    md = compute_metadata(cleaned, source_url="http://x")  # default business
    # Business metadata must keep its exact keys and NOT gain entity_type/field_coverage.
    assert "entity_type" not in md and "field_coverage" not in md, md.keys()
    for k in ("with_name", "with_phone", "with_email", "with_website",
              "with_address", "with_description", "with_category", "with_contacts"):
        assert k in md, f"missing business count {k}"
    print("  business regression OK -> unchanged 9-key shape + business metadata")


def test_csv_columns():
    try:
        from app import _records_to_csv
    except Exception as e:  # heavy deps may be unavailable outside the venv
        print(f"  CSV test skipped (could not import app: {str(e)[:60]})")
        return
    recs = apply_selectors(GPU_HTML, GPU_SELECTORS)
    csv_text = _records_to_csv(recs, entity_type="product")
    header = csv_text.splitlines()[0]
    for col in ("model", "chipset", "memory", "tdp", "price", "detail_url"):
        assert col in header, f"{col} missing from CSV header: {header}"
    print("  CSV dynamic columns OK ->", header)


if __name__ == "__main__":
    print("test_dynamic_extract_clean_metadata"); test_dynamic_extract_clean_metadata()
    print("test_dynamic_dedup_and_drop"); test_dynamic_dedup_and_drop()
    print("test_role_normalization"); test_role_normalization()
    print("test_business_regression"); test_business_regression()
    print("test_csv_columns"); test_csv_columns()
    print("\nALL PASS")
