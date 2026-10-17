# ADR-0002 — Chunking is structure-native and deterministic

- **Status:** accepted · 2026-10-17
- **Decision:** a chunk is the unit the source already delimits (message, email, ticket, wiki section, meeting turn window, PR description or review). Long units split at headings, then paragraphs, under a token cap. Neighbours link by `NEXT`; every chunk carries a header (title, space, author alias, day).
- **Why:** the corpora are natively segmented, so a model choosing boundaries adds cost and nondeterminism without adding signal. Deterministic chunks make ingestion idempotent and every span offset replayable.
- **Rejected:** LLM-driven ("agentic") chunking; fixed-size windows with duplicated overlap (breaks exact span provenance and inflates the index).
- **Where models do work:** claim and decision extraction, quote-verified, on self-hosted weights.
- **Revisit when:** a measured retrieval miss is traced to a boundary that structure cannot express.
