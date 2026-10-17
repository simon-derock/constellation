# ADR-0004 — Model roles: one set of weights per role, free at the point of use

- **Status:** accepted · 2026-10-17
- **Text embeddings:** Qwen3-Embedding-0.6B (Apache-2.0, 32k context, MRL). Corpus embedded on Kaggle from the open weights; queries and incremental live documents embedded on Workers AI (`@cf/qwen/qwen3-embedding-0.6b`, probed 2026-10-17: 1,024 dimensions). AC-MOD-01 bounds the cross-runtime Recall@10 gap at 0.5 points.
- **Bake-off:** bge-m3 and EmbeddingGemma-300m, both open and free on Workers AI, compete on judge-free Recall@10 and MRR; the winner deploys the same way.
- **Reranker:** bge-reranker-base on Workers AI and Kaggle; kept only if its ablation wins.
- **Voice:** EmbeddingGemma 2 audio tower, batch only.
- **LLMs:** an open-weights model on Workers AI answers live and in benchmark runs (Kaggle-hosted weights when a run exceeds the daily quota); Cohere Command is the second model and the judge, so judge and answerer never share a family.
- **Rejected for the request path:** Cohere embeddings (trial: 1,000 calls/month across endpoints); Voyage API (3 requests/minute without a card); OpenRouter free (50 requests/day); HF ZeroGPU (5 GPU-minutes/day); any model on the 0.1-CPU API host.
- **Revisit when:** the bake-off or a recorded run contradicts a role, or a quota is exhausted in practice.
