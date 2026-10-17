# Gold-label disputes

Answer-key entries that contradict their own source data. Each is reported upstream; scores are always published raw (official) and audited (disputes excluded) side by side (PLAN_SPEC §16.3).

## EpistemicBench (OrgForge `f2a1ab2`)

| Question | Key | Evidence from the simulator's own rules (OrgForge `1da5e4b`, cap lifted) |
|---|---|---|
| `counterfactual_EVT-44-pr_review-1534_pr_gap_detected` | outcome changes | 2 other `pr_gap_detected` causes of the same effect: `EVT-44-pr_review-1535`, `EVT-45-pr_review-1569` |
| `counterfactual_EVT-35-knowledge_gap_detected-1471_involves_gap` | outcome changes | 204 other `involves_gap` causes of the same incident, e.g. `EVT-30-knowledge_gap_detected-1390` |
| `counterfactual_EVT-27-pr_review-1560_review_triggers_revision` | outcome changes | 1 other `review_triggers_revision` cause: `EVT-28-pr_review-1531` |
| `counterfactual_EVT-14-knowledge_gap_detected-1365_involves_gap` | outcome changes | 344 other `involves_gap` causes of the same incident, e.g. `EVT-10-knowledge_gap_detected-1211` |

**Probable cause:** question generation samples 15 links per type after a random shuffle, so sibling causes outside the sample are invisible to the labeller, while the benchmark's negative questions are defined precisely by sibling causes.
