import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

JOBS = ("redwood_bm25", "redwood_dense", "redwood_full", "redwood_sparse", "redwood_rewrite")
ROOT = Path("jobs/redwood_bm25")


def load(job: str = "redwood_bm25") -> ModuleType:
    spec = importlib.util.spec_from_file_location(job, Path("jobs") / job / "run.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_kaggle_job_is_pinned_to_exactly_the_bytes_in_pins() -> None:
    pins = json.loads(Path("pins/datasets.json").read_text())["redwood"]
    pinned = {f["path"]: (f["size"], f["sha256"]) for f in pins["files"]}
    job = load()
    assert pins["revision"] == job.REVISION
    for name, expected in job.FILES.items():
        assert pinned[name] == expected, name


def test_the_job_names_a_full_commit_so_the_code_that_ran_is_recoverable() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", load().COMMIT)


def test_the_kernel_is_private_cpu_only_and_has_internet_for_the_pinned_download() -> None:
    meta = json.loads((ROOT / "kernel-metadata.json").read_text())
    assert meta["is_private"] is True
    assert meta["enable_gpu"] is False
    assert meta["enable_internet"] is True
    assert meta["code_file"] == "run.py"


def test_list_columns_stored_as_text_are_parsed_and_junk_becomes_empty() -> None:
    parse = load().as_list
    assert parse("['dsid_1', 'dsid_2']") == ["dsid_1", "dsid_2"]
    assert parse(["a"]) == ["a"]
    assert parse("[]") == []
    assert parse(None) == []


@pytest.mark.parametrize("job", JOBS)
def test_every_job_is_pinned_to_the_same_bytes_and_a_full_commit(job: str) -> None:
    pins = json.loads(Path("pins/datasets.json").read_text())["redwood"]
    pinned = {f["path"]: (f["size"], f["sha256"]) for f in pins["files"]}
    module = load(job)
    assert pins["revision"] == module.REVISION
    assert re.fullmatch(r"[0-9a-f]{40}", module.COMMIT)
    for name, expected in module.FILES.items():
        assert pinned[name] == expected, (job, name)


def test_the_dense_job_pins_its_model_to_a_revision_and_requires_an_accelerator() -> None:
    module = load("redwood_dense")
    assert module.MODEL == "BAAI/bge-base-en-v1.5"
    assert re.fullmatch(r"[0-9a-f]{40}", module.MODEL_REVISION)
    meta = json.loads(Path("jobs/redwood_dense/kernel-metadata.json").read_text())
    assert meta["enable_gpu"] is True
    assert meta["is_private"] is True


def test_passages_cover_the_head_and_the_text_after_it_and_skip_scraps() -> None:
    passages = load("redwood_dense").passages_of
    long_body = "x" * 2_000
    out = passages("Title", long_body)
    assert len(out) == 2
    assert out[0].startswith("Title\n")
    assert passages("Title", "short") == ["Title\nshort"]
    assert len(passages("Title", "y" * 1_250)) == 1
