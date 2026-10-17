# Audit — Track 02 memory: clone fleet and contention

- **Date:** 2026-10-18 · **Engine:** FalkorDB 4.22.1 (digest-pinned) in a local container, one process, laptop CPU (i5-10300H)
- **Command:** `uv run python tools/bench_memory.py --port <port>` (1,000 clones; 32 agents x 100 updates)

## Result (after the backoff fix below)
| Measure | Value |
|---|---|
| Clones created with `GRAPH.COPY` | 1,000 |
| Clone time p50 / p95 / p99 | 100.02 / 101.31 / 102.21 ms |
| Read latency p50 / p99 | 0.36 / 1.10 ms |
| Isolation probes (every 5th clone) | 200 |
| **Cross-tenant reads** | **0** |
| Concurrent agents x updates | 32 x 100 = 3,200 |
| Final counter value | 3,200 |
| **Lost updates** | **0** |
| Conflicts retried (compare-and-set lost, re-read, retried) | 12,891 (4.0 per update) |
| Throughput under full contention | 506 updates/s |

## Two defects the benchmark found
1. **Writer starvation.** The first version retried a lost compare-and-set at once, up to 200 times. Under 32 writers a worker exhausted its retries and died, ending a run at 1,210 of 1,280 increments. No update was ever lost (the counter never exceeded what completed), but a writer was starved. Retries now follow jittered exponential backoff bounded by a deadline instead of a count. Same contention, 276 → 506 updates/s, retries per update 5.3 → 4.0. The 32-agent test passes 6 of 6 repeats.
2. **`GRAPH.COPY` needs headroom to fork.** The command forks the server process. With about 1.3 GB of host memory free next to three FalkorDB containers, a copy failed with `could not fork`, and on one earlier run the server exited with a segmentation fault during a copy (container exit 139, crash report shows a module fork in progress). A bare loop of 2,500 copies on a fresh container did not crash, so the trigger is memory pressure rather than the number of graphs; the server-side crash on the failure path is unconfirmed and would be a FalkorDB report, not ours to claim. Provisioning now falls back to building the empty template's schema directly when the fork fails, which yields the identical graph; it is unit-tested against a fork-failing database. This matters on the 512 MB free host, where forking will often fail.

## How to read it
- A lost compare-and-set is never a lost update: the writer re-reads and retries, so contention shows as retries and the final value equals the serial replay.
- Clone time is flat near 100 ms regardless of fleet size up to 1,000: a fixed per-copy cost, not growth with the number of graphs.

## Limits
- One process and one machine; no network latency between agent and database.
- Isolation probes sample every fifth clone; the integration suite checks every clone in a 60-graph fleet.
- Numbers are for the local container, not the hosted free tier.
