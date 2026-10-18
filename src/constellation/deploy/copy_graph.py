import argparse

from falkordb import FalkorDB


def copy_graph(source: FalkorDB, target: FalkorDB, graph: str) -> None:
    # DUMP/RESTORE moves the engine's own serialization, so the copy answers every query exactly as the original does;
    # the engine embeds the graph's name in it, which is why the name cannot change on the way
    blob = source.connection.dump(graph)
    if blob is None:
        raise LookupError(f"no graph named {graph!r} on the source server")
    if target.connection.exists(graph):
        raise FileExistsError(f"{graph!r} already exists on the target; refusing to overwrite it")
    target.connection.restore(graph, 0, blob)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy one graph between FalkorDB servers on this machine")
    parser.add_argument("graph")
    parser.add_argument("--from-port", type=int, required=True)
    parser.add_argument("--to-port", type=int, required=True)
    args = parser.parse_args()
    source = FalkorDB(host="127.0.0.1", port=args.from_port)
    copy_graph(source, FalkorDB(host="127.0.0.1", port=args.to_port), args.graph)
    print(f"copied {args.graph}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
