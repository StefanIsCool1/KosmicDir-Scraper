"""Verify the cleaner fixes against the existing poisoned hoa-usa output.

Re-runs the (updated) cleaner over the on-disk structured JSON so we can
see before/after counts without re-scraping the site.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Bot"))

from cleaner import clean_members, _is_label_name  # noqa: E402


def main():
    path = os.path.join(
        os.path.dirname(__file__), "Data-dump", "hoa-usa_com_structured.json"
    )
    with open(path) as f:
        before = json.load(f)

    # Stats before
    before_count = len(before)
    before_label_names = [m["company_name"] for m in before
                          if _is_label_name(m.get("company_name", ""))]
    before_emails = []
    for m in before:
        for c in m.get("contacts") or []:
            if c.get("email"):
                before_emails.append(c["email"].lower())
    from collections import Counter
    email_counts = Counter(before_emails)
    poisoned = [(e, c) for e, c in email_counts.most_common(5) if c >= 5]

    print("=" * 60)
    print("BEFORE")
    print("=" * 60)
    print(f"  Total records:           {before_count}")
    print(f"  Label-name records:      {len(before_label_names)}")
    if before_label_names:
        print(f"    → {', '.join(repr(n) for n in before_label_names[:5])}")
    print(f"  Most common emails:")
    for e, c in poisoned:
        pct = 100 * c / before_count
        print(f"    {c:>3} records ({pct:>4.1f}%)  {e}")

    # Run cleaner
    print()
    print("=" * 60)
    print("RUNNING UPDATED CLEANER")
    print("=" * 60)
    # Cleaner mutates in place — copy first so we keep a pristine before
    before_copy = json.loads(json.dumps(before))
    after = clean_members(before_copy)

    # Stats after
    after_label_names = [m["company_name"] for m in after
                         if _is_label_name(m.get("company_name", ""))]
    after_emails = []
    for m in after:
        for c in m.get("contacts") or []:
            if c.get("email"):
                after_emails.append(c["email"].lower())
    after_email_counts = Counter(after_emails)

    print()
    print("=" * 60)
    print("AFTER")
    print("=" * 60)
    print(f"  Total records:           {len(after)}   (was {before_count})")
    print(f"  Label-name records:      {len(after_label_names)}   (was {len(before_label_names)})")
    print(f"  Records with any email:  {sum(1 for m in after if any(c.get('email') for c in m.get('contacts') or []))}")
    print(f"  Most common emails:")
    for e, c in after_email_counts.most_common(5):
        pct = 100 * c / max(len(after), 1)
        print(f"    {c:>3} records ({pct:>4.1f}%)  {e}")

    # Sanity assertions
    print()
    print("=" * 60)
    print("ASSERTIONS")
    print("=" * 60)
    ok = True

    if after_label_names:
        print(f"  [FAIL] Still has label-name records: {after_label_names[:3]}")
        ok = False
    else:
        print(f"  [OK  ] No label-name records remain")

    if "hoausa@associaonline.com" in (e for e in after_emails):
        offender_count = sum(1 for e in after_emails if e == "hoausa@associaonline.com")
        if offender_count >= 5:
            print(f"  [FAIL] Shared email 'hoausa@associaonline.com' still on {offender_count} records")
            ok = False
        else:
            print(f"  [OK  ] Shared email reduced to {offender_count} record(s) (below threshold)")
    else:
        print(f"  [OK  ] Shared email 'hoausa@associaonline.com' removed entirely")

    print()
    print(f"Result: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
