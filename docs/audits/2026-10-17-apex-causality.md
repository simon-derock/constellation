# Audit — Apex causal index vs EpistemicBench COUNTERFACTUAL keys

- **Date:** 2026-10-17 · **Data:** Apex `f2a1ab2` · **Rules:** OrgForge `1da5e4b`, vendored verbatim (`src/constellation/_vendor/orgforge_causal.py`, sha256-pinned)
- **Command:** `uv run python tools/audit_apex_causality.py`
- **Result:** 2,313 links indexed · questioned links present **21/21** · outcome agreement **17/21**

## Method
The simulator's own `CausalLinkIndexer.build()` runs unmodified over the corpus events with one difference: its 15-links-per-type cap (a sampling device for question generation) is lifted, so the brain keeps every link. Events run chronologically, because each rule returns the *first* matching effect.

| Step | Event order | Questioned links present |
|---|---|---|
| 1 | corpus export order | 19/21 |
| 2 | chronological `(day, timestamp)` | **21/21** |

Counterfactual rule: removing a cause changes its effect unless another cause of the **same mechanism** leads to the same effect (the benchmark's own negative questions are built exactly this way, from sibling links).

## Disagreements
All four are listed in [`gold-disputes.md`](gold-disputes.md) with evidence. In each, the key says the outcome would change, while the simulator's rules, applied without the sampling cap, find independent same-mechanism causes of the same effect.

## Limits
- Labels and rules come from the same simulator; agreement checks fidelity, not independent truth.
- Answers to COUNTERFACTUAL questions are produced by the agent from graph evidence; this audit measures the evidence layer.
