import argparse
import gzip
import hashlib
import os
import re
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

# a graph snapshot is the only thing the container downloads at boot, and it comes only from this repository's releases
_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LIMIT = 200 * 1024 * 1024


class RestoreError(Exception):
    pass


def fetch_https(url: str, limit: int) -> bytes:
    # origin checked by the caller before this is reached; the read is capped so a hostile server cannot fill the disk
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310  # nosec B310
        data: bytes = response.read(limit + 1)
    if len(data) > limit:
        raise RestoreError("snapshot exceeds the size limit")
    return data


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in _HOSTS


def restore(
    dest: Path,
    url: str,
    sha256: str,
    fetch: Callable[[str, int], bytes] = fetch_https,
    limit: int = _LIMIT,
) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        # local state wins: a restart must never overwrite newer data with an older snapshot
        return
    if not url:
        print("no SNAPSHOT_URL: starting with an empty graph", file=sys.stderr)
        return
    if not _SHA256.fullmatch(sha256):
        raise RestoreError("SNAPSHOT_SHA256 must be a 64-character lowercase sha256")
    if not _allowed(url):
        raise RestoreError(f"{urlsplit(url).hostname!r} is not an allowed snapshot source")
    data = fetch(url, limit)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RestoreError("downloaded snapshot does not match the pinned sha256")
    payload = gzip.decompress(data) if url.endswith(".gz") else data
    dest.parent.mkdir(parents=True, exist_ok=True)
    # written beside the target and renamed into place: a crash never leaves a half-written snapshot as the graph
    handle, temp = tempfile.mkstemp(dir=dest.parent, prefix=".restore-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(payload)
        Path(temp).replace(dest)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="install the pinned graph snapshot before FalkorDB starts")
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        restore(args.dest, os.environ.get("SNAPSHOT_URL", ""), os.environ.get("SNAPSHOT_SHA256", ""))
    except RestoreError as err:
        print(f"snapshot restore refused: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
