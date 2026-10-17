import argparse
import json
import statistics
import sys
import threading
import time
import uuid
from collections.abc import Sequence

from falkordb import FalkorDB

from constellation.memory.store import MemoryStore

# measures Track 02 on whatever FalkorDB it is pointed at: clone fleet latency, isolation, and CAS under contention


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)


def fleet(db: FalkorDB, clones: int, probes: int) -> dict[str, object]:
    store = MemoryStore(db, tenant=f"bench{uuid.uuid4().hex[:6]}")
    provision_ms: list[float] = []
    for i in range(clones):
        start = time.perf_counter()
        store.provision(f"u{i:04d}")
        provision_ms.append((time.perf_counter() - start) * 1_000)
        store.write_fact(f"u{i:04d}", "owner", f"u{i:04d}", expected_ver=0)
    read_ms: list[float] = []
    cross = 0
    for i in range(0, clones, max(1, clones // probes)):
        start = time.perf_counter()
        fact = store.read_fact(f"u{i:04d}", "owner")
        read_ms.append((time.perf_counter() - start) * 1_000)
        cross += fact is None or fact.value != f"u{i:04d}"
    return {
        "clones": clones,
        "provision_ms": {"p50": pct(provision_ms, 0.5), "p95": pct(provision_ms, 0.95), "p99": pct(provision_ms, 0.99)},
        "read_ms": {"p50": pct(read_ms, 0.5), "p99": pct(read_ms, 0.99)},
        "isolation_probes": len(read_ms),
        "cross_tenant_reads": cross,
    }


def contention(db: FalkorDB, agents: int, increments: int) -> dict[str, object]:
    store = MemoryStore(db, tenant=f"cas{uuid.uuid4().hex[:6]}")
    store.provision("shared")
    store.write_fact("shared", "counter", "0", expected_ver=0)
    retries: list[int] = []

    def worker() -> None:
        retries.append(
            sum(store.update_fact("shared", "counter", lambda v: str(int(v) + 1)).retries for _ in range(increments))
        )

    threads = [threading.Thread(target=worker) for _ in range(agents)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start
    fact = store.read_fact("shared", "counter")
    final = int(fact.value) if fact else -1
    return {
        "agents": agents,
        "updates": agents * increments,
        "final_value": final,
        "lost_updates": agents * increments - final,
        "conflicts_retried": sum(retries),
        "updates_per_second": round(agents * increments / elapsed),
        "retries_per_update_mean": round(statistics.mean(r / increments for r in retries), 2),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track 02 benchmark")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--clones", type=int, default=1_000)
    parser.add_argument("--agents", type=int, default=32)
    parser.add_argument("--increments", type=int, default=100)
    args = parser.parse_args(argv)
    db = FalkorDB(port=args.port)
    print(
        json.dumps(
            {"fleet": fleet(db, args.clones, 200), "contention": contention(db, args.agents, args.increments)}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
