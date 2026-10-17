# ADR-0001 — FalkorDB 4.22.x is the primary engine

- **Status:** accepted · 2026-10-17
- **Decision:** run `falkordb/falkordb:v4.22.1`, pinned by digest `sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a`, in tests, CI and production. Engine 6.0.x runs as a smoke matrix only.
- **Why:** 4.22 ships the algorithms our agents call as tools (shortest paths, A*, Yen's k-shortest, PageRank, WCC, betweenness, CDLP); the Rust 6.0 line has not ported all of them yet. Proofs must replay against the exact engine that produced them, so the digest is part of every proof.
- **Rejected:** `latest` tags (silent drift breaks replay); 6.0.x as primary (missing algorithms); FalkorDBLite (predates 6.0, different packaging from production).
- **Evidence:** `tests/integration/test_read_port.py` runs on the pinned digest locally and in CI; the engine itself refuses writes sent through `GRAPH.RO_QUERY`.
- **Revisit when:** 6.0.x passes every gate on the same suite and is faster; publish the comparison either way.
