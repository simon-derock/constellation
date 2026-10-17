import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Kaggle kernel: BM25 over all 511,962 EnterpriseRAG-Bench documents, scored with judge-free retrieval metrics.
# Runs unattended on free CPUs. The package comes from the public repository at the commit named in COMMIT, so the
# code that produced a result is the code in the repository.
COMMIT = "5b41c2611e92737cc59018e46fac7748539e4ec9"
REPO = "https://github.com/simon-derock/constellation"
DATASET = "onyx-dot-app/EnterpriseRAG-Bench"
REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"
# size and sha256 from pins/datasets.json; a drift test keeps these identical to the pins
FILES = {
    "data/documents/test.parquet": (1409893131, "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"),
    "data/questions/test.parquet": (408737, "e25066f4eff3843dd0f3df0d1348113471e072e75007ffe390a0aa83f2a80af2"),
}
OUT = Path(os.environ.get("OUT_DIR", "/kaggle/working"))
MAX_DOCS = int(os.environ.get("MAX_DOCS", "0"))
DATA_DIR = os.environ.get("DATA_DIR", "")
KS = (1, 5, 10, 50, 100)
MAX_CHARS = 40_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str) -> Path:
    from huggingface_hub import hf_hub_download

    local = Path(DATA_DIR) / name if DATA_DIR else None
    path = local if local else Path(hf_hub_download(DATASET, name, repo_type="dataset", revision=REVISION))
    size, expected = FILES[name]
    if path.stat().st_size != size or sha256(path) != expected:
        raise SystemExit(f"integrity failure for {name}")
    print(f"verified {name}", flush=True)
    return path


def as_list(value: object) -> list[str]:
    # the dataset stores list columns as their Python repr
    if isinstance(value, str):
        value = ast.literal_eval(value)
    return [str(v) for v in value] if isinstance(value, list | tuple) else []


def main() -> int:
    try:
        import constellation  # noqa: F401 — already installed, as in a local smoke run
    except ImportError:
        # arguments are constants: a fixed repository URL and a pinned commit, never caller input
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--no-deps", f"git+{REPO}@{COMMIT}"])  # noqa: S603
    import pyarrow.parquet as pq

    from constellation.eval.retrieval import evaluate
    from constellation.retrieval.bm25 import Bm25Index

    started = time.time()
    docs_path, questions_path = fetch("data/documents/test.parquet"), fetch("data/questions/test.parquet")
    ids: list[str] = []

    def batches():  # type: ignore[no-untyped-def]
        reader = pq.ParquetFile(docs_path)
        for batch in reader.iter_batches(batch_size=4_000, columns=["doc_id", "title", "content"]):
            rows = batch.to_pydict()
            ids.extend(rows["doc_id"])
            yield [f"{t}\n{c[:MAX_CHARS]}" for t, c in zip(rows["title"], rows["content"], strict=True)]
            if MAX_DOCS and len(ids) >= MAX_DOCS:
                return
            if len(ids) % 40_000 < 4_000:
                print(f"indexed {len(ids)} documents in {time.time() - started:.0f}s", flush=True)

    index = Bm25Index.build(batches())
    built = time.time()
    print(
        f"index: {index.documents} documents, {index.nbytes / 1e9:.2f} GB, built in {built - started:.0f}s", flush=True
    )

    questions = pq.read_table(questions_path).to_pylist()
    rankings = {q["question_id"]: [ids[i] for i, _ in index.search(q["question"], k=max(KS))] for q in questions}
    gold = {q["question_id"]: set(as_list(q["expected_doc_ids"])) for q in questions}
    types = {q["question_id"]: q["question_type"] for q in questions}
    metrics = evaluate(rankings, gold, types, ks=KS)
    result = {
        "commit": COMMIT,
        "dataset_revision": REVISION,
        "method": "BM25 (k1=1.2, b=0.75) over hashed unigrams, English stopwords, title + first 40,000 characters",
        "max_docs": MAX_DOCS or None,
        "documents": index.documents,
        "index_gb": round(index.nbytes / 1e9, 3),
        "index_seconds": round(built - started),
        "total_seconds": round(time.time() - started),
        "metrics": metrics,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (OUT / "rankings.json").write_text(json.dumps(rankings) + "\n")
    print(json.dumps({k: v for k, v in metrics.items() if k != "by_type"}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
