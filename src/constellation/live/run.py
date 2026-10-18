import argparse
import os
import time
from collections.abc import Mapping

from falkordb import FalkorDB

from constellation.graph.write import WritePort
from constellation.live.github import GitHubClient
from constellation.live.graph import LiveGraph
from constellation.live.sync import Syncer

_MIN_KEY = 16


def credentials(env: Mapping[str, str]) -> tuple[str, str]:
    token, key = env.get("GITHUB_TOKEN", ""), env.get("PSEUDONYM_KEY", "")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required: unauthenticated reads are too few for an organisation")
    if len(key) < _MIN_KEY:
        raise SystemExit(f"PSEUDONYM_KEY must be at least {_MIN_KEY} characters")
    return token, key


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a public GitHub organisation into the live graph")
    parser.add_argument("--org", default="FalkorDB")
    parser.add_argument("--graph", default="brain:falkordb")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--every", type=int, default=0, help="seconds between syncs; 0 runs once")
    args = parser.parse_args()
    token, key = credentials(os.environ)
    db = FalkorDB(host=args.host, port=args.port)
    syncer = Syncer(GitHubClient(token), LiveGraph(db, WritePort(db), args.graph), key, clock=lambda: int(time.time()))
    while True:
        report = syncer.run(args.org)
        print(report, flush=True)
        if not args.every:
            return 1 if report.rate_limited else 0
        time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
