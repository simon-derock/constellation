import gzip
import hashlib
from pathlib import Path

import pytest

from constellation.deploy.restore import RestoreError, restore

BODY = b"REDIS0012 pretend snapshot bytes"
GOOD_URL = "https://github.com/simon-derock/constellation/releases/download/snapshot-apex/apex.rdb"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Fetch:
    def __init__(self, data: bytes) -> None:
        self.data, self.urls = data, []  # type: bytes, list[str]

    def __call__(self, url: str, limit: int) -> bytes:
        self.urls.append(url)
        if len(self.data) > limit:
            raise RestoreError("snapshot exceeds the size limit")
        return self.data


def test_a_verified_snapshot_is_installed_atomically(tmp_path: Path) -> None:
    dest = tmp_path / "dump.rdb"
    restore(dest, GOOD_URL, sha(BODY), fetch=Fetch(BODY))
    assert dest.read_bytes() == BODY
    assert [p.name for p in tmp_path.iterdir()] == ["dump.rdb"]


def test_a_gzipped_snapshot_is_verified_as_downloaded_then_unpacked(tmp_path: Path) -> None:
    packed = gzip.compress(BODY)
    dest = tmp_path / "dump.rdb"
    restore(dest, GOOD_URL + ".gz", sha(packed), fetch=Fetch(packed))
    assert dest.read_bytes() == BODY


def test_a_hash_mismatch_installs_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "dump.rdb"
    with pytest.raises(RestoreError, match="sha256"):
        restore(dest, GOOD_URL, sha(b"something else"), fetch=Fetch(BODY))
    assert list(tmp_path.iterdir()) == []


def test_existing_state_is_kept_and_nothing_is_downloaded(tmp_path: Path) -> None:
    dest = tmp_path / "dump.rdb"
    dest.write_bytes(b"local state")
    fetch = Fetch(BODY)
    restore(dest, GOOD_URL, sha(BODY), fetch=fetch)
    assert dest.read_bytes() == b"local state"
    assert fetch.urls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x/y/releases/download/t/a.rdb",
        "https://evil.example/a.rdb",
        "https://github.com.evil.example/a.rdb",
        "file:///etc/passwd",
        "ftp://github.com/a.rdb",
    ],
)
def test_only_https_urls_on_github_hosts_are_fetched(tmp_path: Path, url: str) -> None:
    fetch = Fetch(BODY)
    with pytest.raises(RestoreError, match="not an allowed snapshot source"):
        restore(tmp_path / "dump.rdb", url, sha(BODY), fetch=fetch)
    assert fetch.urls == []


def test_a_missing_or_malformed_hash_is_refused_before_any_download(tmp_path: Path) -> None:
    fetch = Fetch(BODY)
    for bad in ("", "abc", "z" * 64):
        with pytest.raises(RestoreError, match="sha256"):
            restore(tmp_path / "dump.rdb", GOOD_URL, bad, fetch=fetch)
    assert fetch.urls == []


def test_an_oversized_snapshot_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RestoreError, match="size"):
        restore(tmp_path / "dump.rdb", GOOD_URL, sha(BODY), fetch=Fetch(BODY), limit=10)


def test_an_unconfigured_start_is_an_empty_graph_not_a_crash(tmp_path: Path) -> None:
    restore(tmp_path / "dump.rdb", "", "", fetch=Fetch(BODY))
    assert list(tmp_path.iterdir()) == []
