# MEMORY

Present tense of the build. Design: [`PLAN_SPEC.md`](PLAN_SPEC.md) · contract: the tests · history: git.
Read this first, update it last. Under 80 lines, no secrets, no narrative.

## Now
- **Wave:** W1 Apex brain — access model ported (30/30 vs simulator labels); graph load next
- **Gate:** `scripts/gate.sh` green · 82 tests · traceability 2/38
- **Engine:** FalkorDB `v4.22.1@sha256:b0bdcac2…80ae7a` · client `falkordb` 1.8.0
- **Last commit verified in CI:** see Actions; every push runs the full gate

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-INV-03 proof replay | Partial | read port reproduces result hashes (`tests/integration/test_read_port.py`) |
| AC-INV-06 no agent writes | Partial | engine refuses writes through `GRAPH.RO_QUERY` |
| all others (36) | Missing | — |
| (port check) | Done | `tools/audit_apex_access.py` → 30/30 vs PERSPECTIVE labels; `docs/audits/2026-10-17-apex-access-port.md` |

Datasets pinned in `pins/datasets.json` (Apex `f2a1ab2`, Redwood `69916e3`); `python -m constellation.ingest.fetch apex` verifies every byte.

## Next, in order
1. WritePort: batched `UNWIND … MERGE` of Person, Role, Subsystem, Event, Artifact + INVOLVED_IN, PRODUCED, CAN_OPEN; idempotence test.
2. Visibility as read-only Cypher; differential test: graph cone ≡ `access.visible_artifacts` for every actor × sampled days (AC-INV-02).
3. Ownership/escalation intervals from `domain_registry` + lifecycle events; `owner_as_of` with replayable proof.
4. Kaggle job skeleton: Redwood fetch-and-verify inside the kernel.

## Decisions (one line each; `docs/adr/0001–0004` carry the why)
- Engine 4.22.x primary; 6.0.x smoke only.
- Hosting: Vercel web + Render free (FalkorDB + API, 512 MB) + GitHub Releases snapshots + D1 journal; Redwood as recorded runs.
- Embeddings: Qwen3-Embedding-0.6B — Kaggle for corpus, Workers AI for queries (1,024 dims, probed 17 Oct).
- LLMs: Workers AI live; Cohere second model and judge.
- Agent actions file `agent-action` issues in this repo; no sandbox repo.
- Commits land green; red runs are recorded in commit bodies.

## Apex facts (profiled 17 Oct)
- 22,530 rows · 15 columns: `day date timestamp actors tags artifact_ids dept is_incident is_external facts category doc_id doc_type title body`.
- `actors`, `tags`, `artifact_ids`, `facts` are JSON strings; `facts.causal_chain` lists artifact ids in causal order.
- Categories: `artifact` (slack 3,303 · email 610 · confluence 479 · jira 304 · zoom 208 · pr 57 …), `sim_event` (~11k), metrics 5,760.
- `domain_registry.json`: per domain `primary_owner`, `former_owners`, `known_by`, `documentation_coverage` — ownership ground truth.
- EpistemicBench: 78 q = 30 PERSPECTIVE · 21 COUNTERFACTUAL · 27 SILENCE; gate is 78/78.

## Do not repeat
- HF Gradio/Docker Spaces are paid; ZeroGPU and Voyage free tiers cannot carry a request path.
- FalkorDB Cloud free: 100 MB, deleted after 7 idle days.
- Cohere trial: 1,000 calls/month, all endpoints.
- Render free cannot run an embedding model.
- `graph` is a reserved Mermaid word; `test_*` helper names get collected by pytest.
- Apex timestamps drift from the simulation day both ways; the day is the only clock (ADR-0005).
- `falkordb` is untyped: keep it behind `ReadPort`; mypy override is scoped to that module.

## Commands
```bash
scripts/gate.sh                         # full chain, same as CI
uv run pytest -m integration            # FalkorDB testcontainer tests only
uv run python tools/traceability.py --strict   # release gate
```
