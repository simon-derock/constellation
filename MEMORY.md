# MEMORY

Present tense of the build. Design: [`PLAN_SPEC.md`](PLAN_SPEC.md) · contract: the tests · history: git.
Read this first, update it last. Under 80 lines, no secrets, no narrative.

## Now
- **Built:** all three tracks have working code: Apex brain + proofs (T3), memory fleet + actions (T2/T1), API + MCP, web (Ask · Ownership · Live · Act · Scoreboard), deploy bundle, live GitHub tenant (`brain:falkordb`)
- **Gate:** `scripts/gate.sh` green · 480+ Python tests, 50+ web tests · commits only via `scripts/ship.sh`
- **Engine:** FalkorDB `v4.22.1@sha256:b0bdcac2…80ae7a` · client `falkordb` 1.8.0
- **Snapshot:** release `snapshot-20261018` (`brain.rdb.gz`, 6.5 MB, both graphs); image boots in 8 s, 127 MB
- **Web:** premium redesign shipped (warm paper, Instrument Serif + Geist, grain, parallax ghost word, no blue/gradients); video assets in `video/` still use the old look and must be recaptured last
- **Retrieval (see docs/audits/2026-10-18-redwood-retrieval-stack.md):** Cohere rerank is the lever (hit@10 0.738→0.881); passages, feedback, Qwen rewrites did not help; ceiling ~0.92. Kaggle GPU: pass `--accelerator NvidiaTeslaT4` or it queues for an hour
- **Blocked:** Workers AI free neurons exhausted (not reset 40 min after 00:00 UTC); Cohere trial key at its monthly cap. EpistemicBench has 48 of 78 rows; resume with `--resume`.

## Acceptance criteria
| AC | Status | Evidence |
|---|---|---|
| AC-INV-03 proof replay | Partial | read port reproduces result hashes (`tests/integration/test_read_port.py`) |
| AC-INV-06 no agent writes | Partial | engine refuses writes through `GRAPH.RO_QUERY` |
| AC-T3-01 one graph | Partial | Apex loads idempotently (`tests/integration/test_apex_graph.py`) |
| AC-T3-02 who owned what | Partial | `owner_as_of` ≡ timeline at every boundary, 10 domains; registry-only starts flagged |
| AC-T3-03 who could know | Partial | Cypher cone ≡ oracle, every internal actor × 5 days |
| all others (34) | Missing | — |
| (evidence layer) | Done | PERSPECTIVE 30/30 · COUNTERFACTUAL links 21/21, outcomes 17/21 (4 gold disputes) · SILENCE 27/27 + spaces 27/27 — `docs/audits/` |

Datasets pinned in `pins/datasets.json` (Apex `f2a1ab2`, Redwood `69916e3`); `python -m constellation.ingest.fetch apex` verifies every byte.

## Next, in order
1. Finish EpistemicBench when a model answers: `run_epistemic --resume results/raw/epistemic-20261018T003054.jsonl`; publish summary; audit.
2. Read the Redwood dense Kaggle result; publish with an audit; amend ADR-0004 (bge-base, not Qwen3).
3. Deploy: Render blueprint (needs user: `GITHUB_TOKEN`, `PSEUDONYM_KEY` = local `.env` value, `APPROVER_KEY`), Vercel, CNAME, keep-warm pings.
4. Video, README results, PLAN_SPEC accuracy pass, blog post.

## Decisions (one line each; `docs/adr/0001–0004` carry the why)
- Engine 4.22.x primary; 6.0.x smoke only.
- Hosting: Vercel web + Render free (FalkorDB + API, 512 MB) + GitHub Releases snapshots + D1 journal; Redwood as recorded runs.
- Embeddings: bge-base-en-v1.5 on Kaggle GPU for the Redwood corpus (compute budget); Qwen3 stays the plan for live queries.
- LLMs: Workers AI (gpt-oss-20b) live; Cohere second model; both free tiers cap daily/monthly, so the demo caches presets.
- Agent actions file `agent-action` issues in this repo; no sandbox repo.

## Apex facts (profiled 17 Oct)
- 22,530 rows · 15 columns: `day date timestamp actors tags artifact_ids dept is_incident is_external facts category doc_id doc_type title body`.
- `actors`, `tags`, `artifact_ids`, `facts` are JSON strings; `facts.causal_chain` lists artifact ids in causal order.
- Categories: `artifact` (slack 3,303 · email 610 · confluence 479 · jira 304 · zoom 208 · pr 57 …), `sim_event` (~11k), metrics 5,760.
- `domain_registry.json`: per domain `primary_owner`, `former_owners`, `known_by`, `documentation_coverage` — ownership ground truth.
- EpistemicBench: 78 q = 30 PERSPECTIVE · 21 COUNTERFACTUAL · 27 SILENCE; gate is 78/78.

## Agent design (measured 18 Oct, gpt-oss-20b on Workers AI)
- Each track is two Actions deep; event types and mechanisms are schema enums; mechanism labels carry a one-line gloss.
- The verifier fills mechanism, actors, evidence, reasoning from tool results: the model emits only the verdict.
- Fixed prompt+spec overhead fell 30-45%; counterfactual 47k tokens/never solved → ~4.5k tokens, 1.0 on its probe.
- A named mechanism decides cause/effect types (one type pair each); type guesses beside it only hid links.
- Tools validate event ids and return a correctable error; a silent "unlinked" let the model invent ids.

## Live tenant (FalkorDB's public GitHub)
- Keeps titles, states, labels, timestamps; never bodies. People are `adjective-noun-hex` HMAC aliases; bots dropped.
- A claim is `(item, predicate, value)` with `[valid_from, valid_to)`; history is derived on first sight, later changes supersede and never overwrite.
- Claim ids anchor to source time, not sync time, so replays converge. `since` is inclusive: boundary items re-seen, plan is idempotent.
- `PSEUDONYM_KEY` must stay identical between the snapshot and the deployment.

## Do not repeat
- HF Gradio/Docker Spaces are paid; ZeroGPU and Voyage free tiers cannot carry a request path.
- FalkorDB Cloud free: 100 MB, deleted after 7 idle days.
- Cohere trial: 1,000 calls/month; chat is capped but rerank still works. Render free cannot run an embedding model.
- `graph` is a reserved Mermaid word; `test_*` helper names get collected by pytest.
- Causal rules take the first match: run events chronologically (19→21/21 links).
- `_vendor/` is generated and sha256-pinned; regenerate with `tools/vendor_orgforge.py`, never edit.
- Workers AI rejects null fields echoed back from replies (HTTP 400 on turn two): echo only role/content/tool_calls.
- FalkorDB client inlines params as text: strip C0 controls (NUL in 2 Apex summaries broke the load).
- FalkorDB `RESTORE` fails under a different key name (name is inside the dump): copy graphs under the same name.
- `>> .env` appends onto an unterminated last line and corrupts it: check with `awk -F=` (names and lengths only).
- `uv run --with torch` pulls GBs; never. Do not run Docker builds while the gate runs.

## Commands
```bash
scripts/gate.sh                         # full chain, same as CI
uv run pytest -m integration            # FalkorDB testcontainer tests only
uv run python tools/traceability.py --strict   # release gate
```
