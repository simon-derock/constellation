import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

ROOT = Path("jobs/redwood_bm25")


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("redwood_job", ROOT / "run.py")
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
