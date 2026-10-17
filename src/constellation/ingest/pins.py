import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class IntegrityError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PinnedFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Pin:
    repo: str
    revision: str
    licence: str
    files: tuple[PinnedFile, ...]


def load_pins(path: Path) -> dict[str, Pin]:
    raw = json.loads(path.read_text())
    return {
        name: Pin(
            repo=p["repo"],
            revision=p["revision"],
            licence=p["licence"],
            files=tuple(PinnedFile(f["path"], int(f["size"]), f["sha256"]) for f in p["files"]),
        )
        for name, p in raw.items()
    }


def verify(root: Path, pinned: PinnedFile) -> None:
    # size first: a truncated download fails in O(1) before a 1.4 GB hash
    local = root / pinned.path
    if not local.is_file():
        raise IntegrityError(f"missing {pinned.path}")
    if (size := local.stat().st_size) != pinned.size:
        raise IntegrityError(f"size {size} != pinned {pinned.size} for {pinned.path}")
    digest = hashlib.sha256()
    with local.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != pinned.sha256:
        raise IntegrityError(f"sha256 mismatch for {pinned.path}")
