# ADR-0005 — Apex access model and scoring are ported, never inferred

- **Status:** accepted · 2026-10-17
- **Decision:** Apex visibility follows OrgForge's published `ActorVisibilityBuilder` (`eval/eval_harness.py`, commit `1da5e4b`): an artifact is visible to an actor if the actor was **directly involved** in the producing event, or the event type is a **broadcast** (`_BROADCAST_CONFIG`) on a subsystem the actor can access; and the artifact's subsystem is in the actor's **role access** (`_ROLE_SUBSYSTEM_ACCESS`); and its timestamp is within the **as-of** horizon. Jira projects add a role gate (`_JIRA_PROJECT_ACCESS`, `agentic_eval_harness-v2.py`).
- **Graph form:** roles, subsystems and involvement become nodes and edges; visibility is a read-only Cypher query, and the bitmaps are derived from it. A Python port of the builder is kept only as the differential oracle.
- **Faithful quirks, kept on purpose:** cones accumulate from business day 1 (pre-simulation history is never "seen"); artifact keys missing from `_ARTIFACT_SUBSYSTEM` (for example `zoom_transcript`) never enter a cone. Changing either would score against a different benchmark.
- **Roles:** from the simulator config that generated the corpus (`third_party/orgforge/config.yaml`), because the dataset omits the org chart. All 30 PERSPECTIVE actors' roles agree with it.
- **Scoring:** EpistemicBench results are computed with the harness's own scorer classes, vendored unmodified and pinned, fed our recorded trajectories. Raw scores are published as the harness defines them.
- **Rejected:** inferring visibility from answer keys (tuning on the test set); a hand-written access model (scores a different question).
- **Revisit when:** OrgForge publishes a newer harness; re-pin and re-run, never mix versions in one run.
