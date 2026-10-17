import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from falkordb import FalkorDB

from constellation.brain.absence import expectations
from constellation.brain.causality import index_causal_links
from constellation.brain.ownership import ownership_timeline
from constellation.graph.write import WritePort
from constellation.ingest.apex import escalation_chains, load_apex, ownership_sources, raw_events
from constellation.ingest.apex_graph import load_causes, load_escalations, load_expectations, load_into, load_ownership
from constellation.ingest.pins import load_pins, verify

CONFIG = Path("third_party/orgforge/config.yaml")


def build(db: FalkorDB, graph: str, raw: Path, pins: Path) -> dict[str, int]:
    # refuse to build from bytes that differ from the pin: every proof names the data it ran on
    for pinned in load_pins(pins)["apex"].files:
        if pinned.path.startswith(("corpus/", "questions/", "supplemental/")):
            verify(raw, pinned)
    corpus = raw / "corpus/corpus-00000.parquet"
    port = WritePort(db)
    apex = load_apex(corpus, CONFIG)
    events = raw_events(corpus)
    facts = ownership_timeline(*ownership_sources(corpus, raw / "supplemental/domain_registry.json"))
    edges = index_causal_links(events)
    found = expectations(events)
    chains = escalation_chains(corpus)
    load_into(port, graph, apex)
    load_ownership(port, graph, facts)
    load_causes(port, graph, edges)
    load_expectations(port, graph, found)
    load_escalations(port, graph, chains)
    return {
        "events": len(apex.events),
        "artifacts": len(apex.artifacts),
        "ownership_facts": len(facts),
        "causal_edges": len(edges),
        "expectations": len(found),
        "escalation_chains": len(chains),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build the brain:apex graph from pinned data")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--graph", default="brain:apex")
    parser.add_argument("--raw", type=Path, default=Path("data/raw/apex"))
    parser.add_argument("--pins", type=Path, default=Path("pins/datasets.json"))
    args = parser.parse_args(argv)
    start = time.perf_counter()
    counts = build(FalkorDB(host=args.host, port=args.port), args.graph, args.raw, args.pins)
    print(" · ".join(f"{k} {v}" for k, v in counts.items()) + f" · {time.perf_counter() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
