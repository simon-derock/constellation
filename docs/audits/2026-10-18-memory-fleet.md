# Audit — Track 02 memory: clone fleet and contention

- **Date:** 2026-10-18 · **Engine:** FalkorDB 4.22.1 (digest-pinned) in a local container, one process, laptop CPU (i5-10300H)
- **Command:** `uv run python tools/bench_memory.py --port <port>` (1,000 clones; 32 agents x 100 updates)

## Result
| Measure | Value |
|---|---|
| Clones created with `GRAPH.COPY` | 1,000 |
| Clone time p50 / p95 / p99 | 99.97 / 101.24 / 103.65 ms |
| Read latency p50 / p99 | 0.58 / 1.70 ms |
| Isolation probes (every 5th clone) | 200 |
| **Cross-tenant reads** | **0** |
| Concurrent agents x updates | 32 x 100 = 3,200 |
| Final counter value | 3,200 |
| **Lost updates** | **0** |
| Conflicts retried (compare-and-set lost, re-read, retried) | 17,076 (5.3 per update) |
| Throughput under full contention | 276 updates/s |

## How to read it
- A lost compare-and-set is never a lost update: the writer re-reads and retries, so contention shows as retries and the final value equals the serial replay.
- Clone time is flat near 100 ms regardless of fleet size up to 1,000, which points to a fixed per-copy cost rather than growth with the number of graphs. This is a measurement on one machine; the hosted free tier is slower and holds fewer graphs (512 MB).

## Limits
- One process and one machine; no network latency between agent and database.
- Isolation probes sample every fifth clone rather than all 1,000; the integration suite checks every clone in a 60-graph fleet.
