"""Ground truth for tests/fixtures/*.html.

A .py data module, not .json — the repo-wide *.json gitignore would silently
drop a JSON truth file (same reason Bot/zip_seeds.py is planned as .py).

Truth counts were established by counting the page's own semantic card
markers (e.g. .fsConstituentItem, .gz-directory-card) — markers the
structural detector never reads, so the tests are independent of the thing
under test. See tests/harvest_fixtures.py for fixture provenance.
"""

# fixture -> {truth: real member-card count on the page,
#             card_class: semantic marker class of ONE card (None when the
#             fixture has no semantic names, e.g. the hashed variant)}
POSITIVE = {
    # 212 GrowthZone cards, each in a div.Rank10.gz-list-col wrapper.
    # Legacy [class*='card'] counter reads 1608 (7.6x) on this page.
    "buildingncw_growthzone.html": {"truth": 212, "card_class": "gz-directory-card"},
    # 50 Finalsite cards under ONE [class*='constituent'] container — the
    # markup that broke the reverted containment-dedup counter.
    "minnetonka_finalsite.html": {"truth": 50, "card_class": "fsConstituentItem"},
    # 100 dentist cards + a 200+ checkbox filter rail that must lose.
    "findadentist_cards.html": {"truth": 100, "card_class": "profile-card-wrapper"},
    # Same page, every class/id rewritten to css-<hash> — the hashed-CSS
    # exit criterion. No semantic names anywhere.
    "findadentist_hashed.html": {"truth": 100, "card_class": None},
    # Same page with class/id attributes REMOVED entirely — forces the
    # positional nth-of-type emission path (hand-written-HTML shape).
    "findadentist_classless.html": {"truth": 100, "card_class": None},
    # 30 aggregator listings, each in a div.result wrapper.
    "superpages_aggregator.html": {"truth": 30, "card_class": "srp-listing"},
    # 153 Drupal person cards in classless wrapper divs; cards carry only a
    # name-link (hyphenated slug) + plain-text titles — no phone/email.
    "berkeley_people.html": {"truth": 153, "card_class": "node-openberkeley-person"},
    # The nav-menu-heavy page: 693 adjacent a.dropdown-option + 401
    # hyphenated-slug industry links — but ALSO a real 20-cafe listing
    # (classless divs: name/address/city rows + a header row, so the run is
    # 21 nodes). The detector must elect the cafes, never the nav runs;
    # test_navheavy_never_elects_nav pins that explicitly.
    "enigma_navheavy.html": {"truth": 20, "card_class": None},
}

# Pages where electing ANY repeated run as member records is a false
# positive: a homepage of menus/forms, and a Tailwind city-link hub (100
# adjacent <a> "cards" with no contact signals).
NEGATIVE = [
    "eatingminnesota_home.html",
    "matchhoa_cityhub.html",
]
