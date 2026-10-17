# STATE

Where the build stands. [`PLAN_SPEC.md`](PLAN_SPEC.md) is the intended design; tests are the contract; this file is the present tense.

## Handoff
- Last updated: 2026-10-17
- Active wave: W0 Foundation
- Branch: `main`
- Last verified command: diagrams rendered with `@mermaid-js/mermaid-cli` 11.4.2 (docs only, no code yet)

## Current state
- Specification frozen: constitution, graph model, Cypher catalogue, gate sheet, hosting, batch jobs, block protocol.
- Every acceptance criterion: **Missing**.
- Measured results: none.

## Next actions, in order
1. `pyproject.toml` with uv, the quality chain, and CI running it on every push.
2. `scripts/check_traceability.py`, failing CI on any AC without a test.
3. FalkorDB 4.22.x in testcontainers, pinned by digest; first integration test.
4. `domain` types: UUIDv5 identifiers, half-open intervals, proof types, with property tests.
5. Dataset pins and manifests for Apex and Redwood; first Kaggle job skeleton.
6. ADR-0003 hosting and ADR-0004 model roles, each with its probe result.

## Decisions
ADRs land in `docs/adr/` as they are taken. Pending: ADR-0001 FalkorDB 4.22.x primary · ADR-0002 structure-native chunking · ADR-0003 no-card hosting · ADR-0004 model roles and the parity check.

## Known failures, do not repeat
- Hugging Face Gradio and Docker Spaces need a paid plan to create (October 2026); do not plan hosting on them.
- The FalkorDB Cloud free tier is 100 MB and deletes idle instances after seven days; it is unfit for a judged demo.
- Cohere trial keys allow 1,000 calls a month across all endpoints; never put them on the request path.
- The Voyage API allows 3 requests a minute without a card; it is a fallback, not the primary query path.
- Render free cannot run an embedding model: 0.1 CPU and 512 MB beside FalkorDB.
- `graph` is a reserved word in Mermaid; never use it as a `classDef` name.
