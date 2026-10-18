# Audit: what moves retrieval on EnterpriseRAG-Bench (Redwood), and what does not

- **Date:** 2026-10-18 · **Data:** EnterpriseRAG-Bench `69916e3` (pins/datasets.json), all 511,962 documents, 500 questions
- **Scored:** 470 questions with at least one expected document; 30 expect none and are counted, not scored
- **Metric:** judge-free hit@k against `expected_doc_ids`. "Hit" means at least one expected document is in the top k. 19.6% of questions need more than one document (completeness averages 6.5, project-related 4.2), so **all-gold-in-top-10 is lower: 0.634 for BM25**.
- **What this is not:** every number here is **plain retrieval over a document store**. FalkorDB's vector index (HNSW) and Cypher are **not** in this pipeline. They run the Apex tenant, not this benchmark. These scores say nothing about the FalkorDB stack.
- **Target:** the spec's gate for AC-EV-03 is Recall@10 ≥ 0.99. **It is not met and not reachable by this method.** The best configuration below scores hit@10 about 0.88.

## The ledger

Every run is in `results/published/`; each kernel is pinned to a commit and a model revision.

| # | Change | hit@10 | MRR | Verdict |
|---|---|---|---|---|
| 0 | BM25, title + first 40k characters | 0.745 | 0.610 | baseline |
| 1 | Dense bge-base, 2 passages per document | 0.532 | 0.418 | worse than BM25 |
| 2 | Dense bge-base, every document in full (2.2M passages) | 0.557 | 0.444 | **truncation was not the main cause** (+2.5 points) |
| 3 | Equal-weight RRF of 0 and 2 | 0.738 | 0.584 | below BM25 at the top, better at depth |
| 4 | Weighted RRF (dense 0.5, k 10), 2-fold cross-validated | 0.764 | – | small, real gain over 0 and 3 |
| 5 | Pseudo-relevance feedback (three strengths) | 0.719 to 0.674 | 0.485 to 0.437 | **hurts** |
| 6 | Passage-level BM25 (best of 12 passages) | 0.726 | 0.588 | no gain alone; lifts the fused candidate ceiling 0.906 to 0.915 |
| 7 | Qwen3-4B query rewrite: hypothetical passage, BM25 | 0.498 | 0.363 | **hurts**: the model invents specifics |
| 8 | Qwen3-4B keywords appended to the question | 0.636 | 0.498 | hurts alone; adds semantic recall at depth |
| 9 | **Cohere `rerank-v4.0-pro` over fused candidates, depth 200, document heads** | **0.881** (95% CI 0.848-0.907) | **0.804** | **the one large gain** |
| 10 | Rerank query-focused passages, depth 60 | 0.843 | 0.730 | below 9, but depth also differs |
| 11 | Rerank query-focused passages, **depth 200** (equal depth to 9) | 0.862 | 0.728 | **passages lose to heads at equal depth** |

## What the evidence says

1. **Reranking is the lever.** A cross-encoder lifts hit@10 by 14 points and hit@1 from 0.50 to 0.75. Semantic questions go from 0.376 to 0.712.
2. **After reranking, candidate recall is the limit.** The reranker reaches about 97% of the candidate ceiling (0.881 against 0.904 at depth 200). The ceiling by source: BM25 + dense 0.906; adding passage BM25 and feedback 0.915; adding the Qwen rewrites 0.915 at 200 and 0.926 at 300.
3. **The remaining misses are semantic questions.** Only 0.76 of them have a gold document in the pool. They are paraphrased on purpose ("top end 80GB accelerator" for H200), and no lexical or small-vector method, and no small open model rewriting the query, bridged that.
4. **Three of my own hypotheses were wrong,** and are recorded so nobody repeats them: document truncation (2), query-focused passages for the reranker (10, 11), and pseudo-relevance feedback (5).

## What would still help, untested

- A stronger query rewriter. The 4B open model hallucinated numbers; a larger model might not. Hosted chat was unavailable for this run (both free quotas were exhausted).
- A larger embedder than bge-base. Qwen3-Embedding-0.6B was not run: it is about 5 times slower and would not fit a free GPU session over 2.2M passages.
- Multi-document questions need an answer-aware stop rule, not a fixed top 10.

## Reproduce

`jobs/redwood_{bm25,dense,full,sparse,rewrite}/` are the Kaggle kernels; `python -m constellation.eval.rerank_eval` reranks and scores. Reranker calls are cached by exact request in `results/cache/rerank/` (not committed).
