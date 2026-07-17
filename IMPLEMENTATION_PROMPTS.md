# Implementation prompts for UNIVERSALITY_PLAN.md

One prompt per **fresh Claude Code chat** in this repo. The plan file is the full spec —
these only carry scope, ordering, and gates. Before Prompt 1: commit the current working
tree. Between phases: one smoke scrape on a known-good site. Order: 1 → 2 → 3/4 (either
order) → 5.

---

## Prompt 1 — Phase 1

Read UNIVERSALITY_PLAN.md and implement Phase 1 only. If git status isn't clean, stop and ask first.

Work fixtures-first: build the tests/fixtures corpus and its pytest tests (per the plan's Verification section) and get them passing against known truth BEFORE writing repetition.py, and wire into the navigator only after the detector passes them. Keep the legacy counter as fallback — never remove it.

Gate: all Phase 1 exit criteria pass, plus one live smoke scrape of a previously-working directory returning the same member count as before. Then commit, and append a "Progress" section to UNIVERSALITY_PLAN.md: what landed, deviations from spec and why, notes for Phase 2.

---

## Prompt 2 — Phase 2

Read UNIVERSALITY_PLAN.md including its Progress section. Verify Phase 1 is committed and the test suite is green; stop and tell me if not. Implement Phase 2 only.

Gate: each Phase 2 exit criterion as a fixture test, full suite green, one live smoke scrape unchanged on a healthy site. Commit + extend the Progress section.

---

## Prompt 3 — Phase 3

Read UNIVERSALITY_PLAN.md including its Progress section. Verify Phases 1–2 are committed and green; stop if not. Implement Phase 3 only.

The credential-exclusion requirement in the Phase 3 spec is non-negotiable — include its test. Don't skip the two AGENTS.md doc updates listed under Sequencing.

Gate: Phase 3 exit criteria, full suite green, one live smoke on the Playground path. Commit + extend Progress.

---

## Prompt 4 — Phase 4

Read UNIVERSALITY_PLAN.md including its Progress section. Verify Phases 1–2 are committed and green; stop if not. Phase 3 is NOT a prerequisite — don't touch its files if it hasn't landed. Implement Phase 4 only.

Gate: Phase 4 exit criteria as fixture tests, full suite green, one live smoke unchanged on a card-grid site. Commit + extend Progress.

---

## Prompt 5 — Phase 5

Read UNIVERSALITY_PLAN.md including its Progress section. Verify Phases 1–3 are committed and green (Phase 3 is a hard dependency); stop if not. Implement Phase 5 only.

Gate: Phase 5 exit criteria (fixture/mocked-form tests plus one live locator smoke), full suite green. Commit + final Progress note marking the plan complete.
