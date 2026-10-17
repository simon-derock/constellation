# MEMORY

Present tense of the build. Design: [`PLAN_SPEC.md`](PLAN_SPEC.md) · contract: the tests · history: git.
Read this first, update it last. Under 80 lines, no secrets, no narrative.

## Now
- **Wave:** W0 Foundation — 4 of 6 blocks done
- **Gate:** `scripts/gate.sh` green · 43 tests · traceability 2/38
- **Engine:** FalkorDB `v4.22.1@sha256:b0bdcac2…80ae7a` · client `falkordb` 1.8.0
- **Last commit verified in CI:** see Actions; every push runs the full gate

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-INV-03 proof replay | Partial | read port reproduces result hashes (`tests/integration/test_read_port.py`) |
| AC-INV-06 no agent writes | Partial | engine refuses writes through `GRAPH.RO_QUERY` |
| all others (36) | Missing | — |

## Next, in order
1. Dataset pins + manifests: Apex (OrgForge) and Redwood revisions, sha256 per file.
2. ADR-0001…0004 (engine, chunking, hosting, models) with the probe evidence already gathered.
3. W1: Apex normaliser → events → idempotent `UNWIND … MERGE`; ownership intervals; first catalogue query.

## Decisions (one line each; ADRs carry the why)
- Engine 4.22.x primary; 6.0.x smoke only.
- Hosting: Vercel web + Render free (FalkorDB + API, 512 MB) + GitHub Releases snapshots + D1 journal; Redwood as recorded runs.
- Embeddings: Qwen3-Embedding-0.6B — Kaggle for corpus, Workers AI for queries (1,024 dims, probed 17 Oct).
- LLMs: Workers AI live; Cohere second model and judge.
- Agent actions file `agent-action` issues in this repo; no sandbox repo.
- Commits land green; red runs are recorded in commit bodies.

## Do not repeat
- HF Gradio/Docker Spaces are paid; ZeroGPU and Voyage free tiers cannot carry a request path.
- FalkorDB Cloud free: 100 MB, deleted after 7 idle days.
- Cohere trial: 1,000 calls/month, all endpoints.
- Render free cannot run an embedding model.
- `graph` is a reserved Mermaid word; `test_*` helper names get collected by pytest.
- `falkordb` is untyped: keep it behind `ReadPort`; mypy override is scoped to that module.

## Commands
```bash
scripts/gate.sh                         # full chain, same as CI
uv run pytest -m integration            # FalkorDB testcontainer tests only
uv run python tools/traceability.py --strict   # release gate
```
