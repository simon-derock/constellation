# Audit — Apex absence detection vs EpistemicBench SILENCE keys

- **Date:** 2026-10-17 · **Data:** Apex `f2a1ab2` · **Rules:** OrgForge `1da5e4b` (`AbsenceCatalogBuilder`, vendored verbatim; decision loop ported per trigger, uncapped)
- **Command:** `uv run python tools/audit_apex_silence.py`
- **Result:** answer agreement **27/27** · search space covers the key's required space **27/27**

## Method
`check_absence` reproduces the catalogue's decision loop for a single trigger using the vendored match-key and search-space methods. Its equivalence to the vendored `build()` is a unit test over real data across four shuffle seeds (`tests/unit/test_absence.py`). No change was made after looking at SILENCE labels; this is the first measurement.

## Why both numbers matter
SILENCE weights trajectory at 70%: a correct "no" without checking the expected search space scores zero on trajectory. `check_absence` returns the search space with every answer, so the agent's tool trace can show the space was covered.

## Limits
- Labels and rules come from the same simulator; agreement checks fidelity, not independent truth.
