import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from huggingface_hub import hf_hub_download

from constellation.ingest.pins import IntegrityError, load_pins, verify


def fetch(name: str, pins_path: Path, dest: Path, skip: frozenset[str] = frozenset()) -> None:
    # download at the pinned revision only, then refuse anything whose bytes differ from the pin
    pin = load_pins(pins_path)[name]
    root = dest / name
    for f in pin.files:
        if f.path in skip:
            continue
        hf_hub_download(pin.repo, f.path, repo_type="dataset", revision=pin.revision, local_dir=root)
        verify(root, f)
        print(f"ok {name}/{f.path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fetch pinned datasets and verify every byte")
    parser.add_argument("name", choices=["apex", "redwood"])
    parser.add_argument("--pins", type=Path, default=Path("pins/datasets.json"))
    parser.add_argument("--dest", type=Path, default=Path("data/raw"))
    parser.add_argument("--skip", action="append", default=[], help="pinned path to leave for batch compute")
    args = parser.parse_args(argv)
    try:
        fetch(args.name, args.pins, args.dest, frozenset(args.skip))
    except IntegrityError as err:
        print(f"integrity failure: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
