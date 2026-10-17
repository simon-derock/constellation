# Security

## Reporting
Open a private advisory: **Security → Report a vulnerability** on this repository. Please do not file public issues for vulnerabilities. Reports are acknowledged within 48 hours.

## Guarantees the code is built to hold
- **Read path is read-only.** Agent and API reads go through `GRAPH.RO_QUERY`; the engine refuses writes even if a query template regresses (tested against the pinned engine).
- **No string-built Cypher from input.** Values are always parameters; the only identifiers spliced into query text pass a strict allowlist pattern.
- **Zero permission leaks** is an invariant with property tests, not a filter (PLAN_SPEC §16).
- **Actions need approval**, are idempotent, and are capped per day.
- **Secrets** live only in platform secret stores; every commit in history is scanned with gitleaks in CI.
- **Supply chain:** locked dependencies, SHA-pinned CI actions, `pip-audit --strict` on every push, weekly Dependabot updates.

## Data
Only public or synthetic data. People in the live tenant are pseudonymised. Benchmark corpora are never re-published in bulk.
