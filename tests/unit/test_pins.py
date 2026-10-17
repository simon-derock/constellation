import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from constellation.ingest.pins import IntegrityError, PinnedFile, load_pins, verify

BODY = b"apex corpus bytes"
GOOD = PinnedFile(path="corpus.parquet", size=len(BODY), sha256=hashlib.sha256(BODY).hexdigest())


def test_verify_accepts_the_pinned_bytes(tmp_path: Path) -> None:
    (tmp_path / "corpus.parquet").write_bytes(BODY)
    verify(tmp_path, GOOD)


def test_verify_rejects_a_size_mismatch_before_hashing(tmp_path: Path) -> None:
    (tmp_path / "corpus.parquet").write_bytes(BODY + b"!")
    with pytest.raises(IntegrityError, match="size"):
        verify(tmp_path, GOOD)


def test_verify_rejects_same_size_different_bytes(tmp_path: Path) -> None:
    (tmp_path / "corpus.parquet").write_bytes(BODY.upper())
    with pytest.raises(IntegrityError, match="sha256"):
        verify(tmp_path, GOOD)


def test_verify_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="missing"):
        verify(tmp_path, GOOD)


def test_repository_pins_are_complete_and_well_formed() -> None:
    pins = load_pins(Path("pins/datasets.json"))
    assert set(pins) == {"apex", "redwood"}
    for pin in pins.values():
        assert len(pin.revision) == 40
        assert all(len(f.sha256) == 64 and f.size > 0 for f in pin.files)
    assert "questions/eval_questions.jsonl" in {f.path for f in pins["apex"].files}
    assert "data/documents/test.parquet" in {f.path for f in pins["redwood"].files}


def test_pins_round_trip_from_json(tmp_path: Path) -> None:
    doc = {"x": {"repo": "o/r", "revision": "a" * 40, "licence": "MIT", "files": [dataclasses.asdict(GOOD)]}}
    (tmp_path / "p.json").write_text(json.dumps(doc))
    assert load_pins(tmp_path / "p.json")["x"].files == (GOOD,)
