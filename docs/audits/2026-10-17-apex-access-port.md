# Audit — Apex access-model port vs EpistemicBench PERSPECTIVE keys

- **Date:** 2026-10-17 · **Commit:** this file's commit · **Data:** Apex `f2a1ab2` (pins/datasets.json) · **Source ported:** OrgForge `1da5e4b`
- **Command:** `uv run python tools/audit_apex_access.py`
- **Result:** agreement **30/30** on `could_actor_have_known`.

## What this measures
Whether `constellation.brain.access` (a line-cited port of OrgForge's `ActorVisibilityBuilder` and `_find_asymmetry_events`, ADR-0005) reproduces the simulator's own PERSPECTIVE labels. It checks the port; it is not an answer score. EpistemicBench scores (answer and trajectory) come later from the harness's scorers.

## How the number moved, in full
| Step | Change | Agreement |
|---|---|---|
| 1 | Faithful port; artifact horizon from corpus row timestamps | 29/30 |
| 2 | Artifact time = earliest producing event's timestamp | 29/30 (fixed one, broke another) |
| 3 | **One clock: the simulation day.** An artifact exists from the day of its earliest producing event | **30/30** |

Steps 2 and 3 were traced to data, not fitted to labels: corpus timestamps drift from the simulation day in both directions (`CONF-RETRO-001` is stamped `2026‑04‑10` with U+2011 hyphens for a day-9 event; `EVT-39-watercooler_chat-1424` is day 39 = Feb 25 but stamped Mar 2). 6 of 4,966 artifact rows carry non-ISO or non-ASCII timestamps, all Confluence. The single-clock rule was already in PLAN_SPEC §6 (`Interval`: one ordinal per clock) before this audit.

## Limits
- Labels come from the same simulator; agreement shows fidelity of the port, not independent truth.
- Held-out validation of the rule (a second simulated company) is planned (PLAN_SPEC §4.3).
