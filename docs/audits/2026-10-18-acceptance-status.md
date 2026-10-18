# Acceptance status: all 38 criteria from PLAN_SPEC, as of 2026-10-18

The spec lists 38 acceptance criteria. This file says what each one actually shows. "Met" means a test in `tests/` asserts it. Nothing is marked met on a target.

| Status | Count | Meaning |
|---|---|---|
| **Met (tested)** | 16 | A test asserts the criterion, and the test runs in the gate |
| **Partly met** | 3 | Part of the criterion is built or configured and measured; the rest is not |
| **Not met** | 4 | The criterion is in scope and its measurement is not yet passing or not yet run |
| **Not built** | 5 | In scope, but the code or data for the measurement does not exist yet |
| **Cut** | 10 | Out of scope for this submission, with the reason given |

## Met (tested)

| ID | Criterion | Evidence |
|---|---|---|
| AC-T1-02 | Every catalogue query is callable as a tool; tool schemas snapshot-tested | `tests/integration/test_mcp_tools.py`, `tests/unit/test_mcp_contract.py` |
| AC-T1-04 | Escalation-path exactness | `tests/integration/test_apex_escalation_graph.py` |
| AC-T1-05 | Every answer carries the full trace | `tests/integration/test_api.py::test_an_answer_carries_the_full_trace` |
| AC-T2-01 | Consolidation rules and re-verified procedure reuse | `tests/integration/test_memory.py` |
| AC-T2-02 | Sessions survive a restart | `tests/integration/test_memory.py` |
| AC-T2-03 | Handoffs keep the state hash and are claimed once | `tests/integration/test_memory.py` |
| AC-T2-04 | 32 concurrent agents, no lost updates | `tests/integration/test_memory.py` |
| AC-T2-05 | No cross-tenant reads across cloned graphs | `tests/integration/test_memory.py` |
| AC-T3-01 | Apex loads idempotently into one graph | `tests/integration/test_apex_graph.py` |
| AC-T3-02 | Ownership as of day D matches the simulator's boundaries | `tests/integration/test_apex_ownership_graph.py` |
| AC-T3-03 | Who could know, equal to the oracle | `tests/integration/test_toolbox.py` |
| AC-T3-05 | A source change makes earlier proofs stale and a fresh proof matches | `tests/integration/test_live_staleness.py` |
| AC-INV-01 | No artifact outside the visibility cone | `tests/integration/test_toolbox.py` |
| AC-INV-03 | Proofs replay to matching hashes | `tests/integration/test_proof.py`, `tests/integration/test_api.py` |
| AC-INV-05 | Executed actions have a recorded approval | `tests/integration/test_actions.py` |
| AC-INV-06 | Agent writes only through the action and memory ports | `tests/integration/test_mcp_tools.py` |

## Partly met

| ID | What is built and measured | What is missing |
|---|---|---|
| AC-T3-07 | Live experts by PageRank, bridges by betweenness with a fixed sample; deterministic over repeated runs (`test_live_search.py`) | Ranking per component, and a ground-truth check |
| AC-EV-04 | Apex ownership exact at every boundary (`AC-T3-02`) | The constructed ground truth for escalation and for the live tenant |
| AC-EV-08 | Staleness proven (`AC-T3-05`); sync interval set to 540 s in `render.yaml` | End-to-end timing not measured on the deployed service |

## Not met

| ID | Measured | Target |
|---|---|---|
| AC-EV-01 | EpistemicBench: 48 of 78 questions recorded, accuracy 0.667 on those, 0 violations; not finished, not published | ≥0.99, 0 violations |
| AC-EV-02 | Not measured: the official EnterpriseRAG answer protocol was not run | ≥99% |
| AC-EV-03 | Redwood hit@10 0.881 with Cohere rerank (95% CI 0.848–0.907) | Recall@10 ≥0.99 |
| AC-T1-06 | Mean 3.42 model calls per question on the 48 recorded rows | ≤1.3 |

## Not built

| ID | Why not built yet |
|---|---|
| AC-T1-01 | Multi-hop questions are not separately scored |
| AC-T1-03 | No MCP routing probe set |
| AC-T2-06 | No benchmark-isolation check across questions |
| AC-EV-05 | No routing@1 measurement |
| AC-EV-07 | No paraphrase, unanswerable and held-out sets scored separately |

## Cut

| ID | Reason |
|---|---|
| AC-AUD-01, AC-AUD-02, AC-AUD-03, AC-AUD-04, AC-EV-06 | No speech or meeting data was built; the spec's audio track is out of scope |
| AC-INV-04 | Meeting claims with playable spans need meeting audio, which is not in scope |
| AC-T3-04 | Decision provenance from meetings; the meeting source is cut |
| AC-T3-06 | Coverage map against the registry was not built |
| AC-INV-02 | No bitmap index, so bitmap-versus-traversal equality is not applicable |
| AC-MOD-01 | Query-embedding parity between two runtimes; the query path uses Cohere, not Workers AI embeddings |

## What this means for submission

The criteria that carry the product are met by tests: the graph model, the time semantics, the access rule, the proof replay, the approval rule, the memory concurrency and the MCP contract. The criteria that carry the benchmark claim are not met yet, and the spec says so. Nothing in the README claims them.
