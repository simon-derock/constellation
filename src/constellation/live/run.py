import argparse
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from falkordb import FalkorDB

from constellation.graph.write import WritePort
from constellation.live.embed import CohereEmbedder, Embedder
from constellation.live.github import GitHubClient
from constellation.live.graph import LiveGraph
from constellation.live.search import embed_pending
from constellation.live.sync import Syncer, SyncReport

_MIN_KEY = 16


def credentials(env: Mapping[str, str]) -> tuple[str, str]:
    token, key = env.get("GITHUB_TOKEN", ""), env.get("PSEUDONYM_KEY", "")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required: unauthenticated reads are too few for an organisation")
    if len(key) < _MIN_KEY:
        raise SystemExit(f"PSEUDONYM_KEY must be at least {_MIN_KEY} characters")
    return token, key


def embedder_from_env(env: Mapping[str, str]) -> Embedder | None:
    # the first key that is set wins; without one, search falls back to the full-text index alone
    for name in ("COHERE_KEY", "COHERE_API_KEY", "COHERENCE_API_KEY"):
        if env.get(name):
            # cached on disk by exact text, so a rebuild or a restart never pays twice for the same title
            return CohereEmbedder(
                env[name], dim=int(env.get("EMBED_DIM", "256")), cache_dir=Path("results/cache/embed")
            )
    return None


def prepare(graph: LiveGraph, embedder: Embedder | None, dim: int, embed_limit: int) -> int:
    # everything the engine-native features need, idempotent: repository edges, the collaboration projection the
    # algorithms run over, the HNSW and full-text indexes, and a vector for every title that lacks a current one
    graph.backfill_repos()
    graph.build_collaboration()
    graph.ensure_search_indexes(dim)
    return embed_pending(graph, embedder, embed_limit) if embedder is not None else 0


def sync_job(db: FalkorDB, env: Mapping[str, str], org: str, graph: str) -> Callable[[], SyncReport]:
    token, key = credentials(env)
    live = LiveGraph(db, WritePort(db), graph)
    syncer = Syncer(GitHubClient(token), live, key, clock=lambda: int(time.time()))
    embedder = embedder_from_env(env)

    def cycle() -> SyncReport:
        report = syncer.run(org)
        # a small cycle: new people link up, and only new or retitled items cost an embedding call
        live.build_collaboration()
        if embedder is not None:
            embed_pending(live, embedder, 500)
        return report

    return cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a public GitHub organisation into the live graph")
    parser.add_argument("--org", default="FalkorDB")
    parser.add_argument("--graph", default="brain:falkordb")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--every", type=int, default=0, help="seconds between syncs; 0 runs once")
    parser.add_argument(
        "--prepare", action="store_true", help="build indexes, collaboration edges and embeddings, then exit"
    )
    parser.add_argument("--embed-limit", type=int, default=100_000)
    args = parser.parse_args()
    db = FalkorDB(host=args.host, port=args.port)
    if args.prepare:
        done = prepare(LiveGraph(db, WritePort(db), args.graph), embedder_from_env(os.environ), 256, args.embed_limit)
        print(f"prepared; embedded {done} titles", flush=True)
        return 0
    sync = sync_job(db, os.environ, args.org, args.graph)
    while True:
        report = sync()
        print(report, flush=True)
        if not args.every:
            return 1 if report.rate_limited else 0
        time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
