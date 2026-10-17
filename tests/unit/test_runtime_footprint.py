import subprocess
import sys

HEAVY = ("polars", "numpy", "scipy", "sklearn", "pyarrow", "pandas")


def test_the_api_runtime_loads_none_of_the_batch_only_libraries() -> None:
    # the free host has 512 MB shared with the database; ingestion and indexing libraries belong to batch jobs
    code = f"import sys, constellation.api.main; print([m for m in {HEAVY!r} if m in sys.modules])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
    assert out.stdout.strip() == "[]", out.stdout
