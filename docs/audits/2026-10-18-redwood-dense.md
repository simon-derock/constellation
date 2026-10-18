# Audit: Redwood dense retrieval and fusion (bge-base, all 511,962 documents)

- **Date:** 2026-10-18 · **Data:** EnterpriseRAG-Bench `69916e3` (pins/datasets.json), all 511,962 documents
- **Code:** commit `4392144`, run as the Kaggle kernel `philipsimon/constellation-redwood-dense` on a free GPU (1,013,762 passages embedded in 4,865 s; 5,212 s in all)
- **Model:** `BAAI/bge-base-en-v1.5` at revision `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`, fp16, query instruction prefix, 320 tokens per passage
- **Raw result:** [`results/published/redwood-dense.result.json`](../../results/published/redwood-dense.result.json) · rankings sha256 `0b4b4bdd0612fac35765eb57b031ca63635b881f086cdb14f083c95112947524`
- **Metric:** judge-free hit and recall against `expected_doc_ids`; 470 of 500 questions are scored, 30 expect no document and are counted but not scored.
- **Method:** each document is two passages of up to 1,200 characters (the head, and what follows it), so only the first 2,400 characters of a document are embedded. Fusion is reciprocal rank fusion of the BM25 and dense rankings.

## Result
| System | hit@1 | hit@10 | hit@100 | recall@10 | MRR |
|---|---|---|---|---|---|
| BM25 | **0.540** | **0.745** | 0.860 | **0.691** | **0.610** |
| Dense (bge-base) | 0.355 | 0.532 | 0.694 | 0.472 | 0.418 |
| Fused (RRF) | 0.472 | 0.728 | **0.875** | 0.669 | 0.555 |

The BM25 row reproduces the earlier CPU run to the digit (hit@10 0.7447), so the two runs share a ranking and an evaluator.

## By question type (hit@10)
| Type | n | BM25 | Dense | Fused |
|---|---|---|---|---|
| basic | 175 | 0.777 | 0.554 | **0.789** |
| completeness | 20 | **0.900** | 0.700 | 0.850 |
| conflicting_info | 20 | 0.900 | 0.700 | **0.950** |
| constrained | 30 | 0.933 | 0.933 | **0.967** |
| intra_document_reasoning | 40 | **0.900** | 0.650 | 0.875 |
| miscellaneous | 20 | 0.850 | 0.900 | **1.000** |
| project_related | 40 | **1.000** | 0.900 | 0.975 |
| semantic | 125 | **0.456** | 0.136 | 0.360 |

## What this says
- Dense retrieval over the head of each document is **worse than BM25 on this corpus**, by 21 points at hit@10. Fusion does not beat BM25 at the top of the ranking (0.728 against 0.745); it helps only at depth (hit@100 0.875 against 0.860) and on some small types.
- The semantic type is the weakest for every system, and dense is the weakest of all on it (0.136). That is the opposite of what the type's name suggests, so the semantic questions are not simply "needs embeddings".
- **Hypotheses, not findings:** embedding only the first 2,400 characters discards the passage that holds the answer for long documents; a 110M-parameter embedder is small for a 512k-document corpus with near-duplicate synthetic text. Neither was tested here.

## What changes
- The retrieval baseline we publish and build against is BM25. Dense vectors are not used for ranking on this corpus until a variant beats it on the same metric.
- ADR-0004's Qwen3-Embedding-0.6B plan was not run on Redwood: bge-base was chosen for the free GPU budget. This result is therefore not evidence about Qwen3. See the amendment in ADR-0004.
- The graph's contribution is measured on the questions retrieval cannot answer (EpistemicBench), not claimed against retrieval here.
