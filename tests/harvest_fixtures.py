"""Harvest tests/fixtures/*.html from Data-dump raw captures.

The Data-dump/{domain}.json raw captures are local-only (gitignored via
*.json); the harvested .html fixtures ARE committed — .html dodges the
repo-wide *.json gitignore on purpose (see UNIVERSALITY_PLAN.md →
Verification). Re-run this script only when refreshing the corpus from new
captures; it is not part of the test run.

Usage:  python3 tests/harvest_fixtures.py   (from the repo root)
"""

import hashlib
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")

# (dump file, capture index, fixture name)
SOURCES = [
    # Positive: GrowthZone chamber — 212 cards, each inside its own
    # div.Rank10.gz-list-col wrapper. The legacy [class*='card'] counter
    # reads 1608 here — the premature-stop (R2) poster child.
    ("buildingncw_org.json", 0, "buildingncw_growthzone.html"),
    # Positive: Finalsite staff directory — 50 fsConstituentItem cards, all
    # under ONE fsConstituentColumnLayout_3 container that itself matches
    # [class*='constituent']. This markup broke the reverted containment-
    # dedup attempt (outermost-only → ~1, leaf-only → ~15 of 50).
    ("www_minnetonkaschools_org.json", 0, "minnetonka_finalsite.html"),
    # Positive: ADA find-a-dentist — 100 utility-class cards under
    # div.profiles-grid-wrapper, plus a 200+ checkbox filter rail the
    # detector must not elect.
    ("findadentist_ada_org.json", 0, "findadentist_cards.html"),
    # Positive: SuperPages aggregator — 30 srp-listing cards, each inside a
    # div.result wrapper.
    ("www_superpages_com.json", 0, "superpages_aggregator.html"),
    # Positive: Drupal person roster — 153 node-openberkeley-person cards in
    # classless wrapper divs with zebra classes.
    ("math_berkeley_edu.json", 1, "berkeley_people.html"),
    # Negative (nav-menu-heavy): enigma city hub — 693 adjacent
    # a.dropdown-option elements are the most repetitive structure on the
    # page; electing them as records is the failure this fixture guards.
    ("enigma_com.json", 0, "enigma_navheavy.html"),
    # Negative: homepage with menus/forms and no listing.
    ("eatingminnesota_com.json", 0, "eatingminnesota_home.html"),
    # Negative: Tailwind city-hub page — 100 adjacent <a> "cards" that are
    # city links (no contact signals, no detail-shaped hrefs), not members.
    ("www_matchhoa_com.json", 0, "matchhoa_cityhub.html"),
]


def _hash_token(tok: str) -> str:
    return "css-" + hashlib.md5(tok.encode()).hexdigest()[:8]


def make_hashed_variant(html: str) -> str:
    """Rewrite every class token and id to a stable css-<hash> token,
    mimicking CSS-modules/styled-components output. Structure, text, and
    attribute layout are untouched — only the names become meaningless, so
    any counter that leans on English class substrings goes blind."""

    def hash_classattr(m):
        toks = m.group(2).split()
        return m.group(1) + " ".join(_hash_token(t) for t in toks) + m.group(3)

    def hash_idattr(m):
        return m.group(1) + _hash_token(m.group(2)) + m.group(3)

    out = re.sub(r'(\bclass=")([^"]*)(")', hash_classattr, html)
    out = re.sub(r"(\bclass=')([^']*)(')", hash_classattr, out)
    out = re.sub(r'(\bid=")([^"]*)(")', hash_idattr, out)
    out = re.sub(r"(\bid=')([^']*)(')", hash_idattr, out)
    return out


def make_classless_variant(html: str) -> str:
    """Drop every class and id attribute — the hand-written-HTML directory
    shape where selector emission has nothing to anchor on and must fall
    back to a positional (nth-of-type) path."""
    out = re.sub(r'\s(?:class|id)="[^"]*"', "", html)
    out = re.sub(r"\s(?:class|id)='[^']*'", "", out)
    return out


def main():
    os.makedirs(FIXTURES, exist_ok=True)
    for dump, idx, name in SOURCES:
        path = os.path.join(REPO, "Data-dump", dump)
        entry = json.load(open(path))[idx]
        html = entry["data"]["raw_html"]
        dest = os.path.join(FIXTURES, name)
        with open(dest, "w") as f:
            f.write(html)
        print(f"{name}: {len(html)} bytes  (from {dump}[{idx}] {entry.get('url', '')[:60]})")
        if name == "findadentist_cards.html":
            for variant, maker in (
                ("findadentist_hashed.html", make_hashed_variant),
                ("findadentist_classless.html", make_classless_variant),
            ):
                out = maker(html)
                with open(os.path.join(FIXTURES, variant), "w") as f:
                    f.write(out)
                print(f"{variant}: {len(out)} bytes  (synthetic variant)")


if __name__ == "__main__":
    main()
