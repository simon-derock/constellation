import ast
import gc
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

# Kaggle kernel: sparse retrieval variants over all 511,962 EnterpriseRAG-Bench documents on a free CPU, each
# measured against the plain document-level BM25 baseline with the same judge-free metrics:
#   1. pseudo-relevance feedback (the first hits' vocabulary joins the query), for questions phrased in other words
#   2. passage-level BM25 (a document ranks where its best 1,200-character passage ranks), so a specific detail is
#      not diluted by the length of a long thread
# The package comes from the public repository at COMMIT; the candidates are exported for a reranker to use elsewhere.
COMMIT = "18af1583670257bc6306a2fa88dff204f94187f8"
REPO = "https://github.com/simon-derock/constellation"
DATASET = "onyx-dot-app/EnterpriseRAG-Bench"
REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"
FILES = {
    "data/documents/test.parquet": (1409893131, "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"),
    "data/questions/test.parquet": (408737, "e25066f4eff3843dd0f3df0d1348113471e072e75007ffe390a0aa83f2a80af2"),
}
OUT = Path("/kaggle/working")
KS = (1, 5, 10, 50, 100, 200)
DEPTH = max(KS)
MAX_CHARS = 40_000
PASSAGE_CHARS = 1_200
MAX_PASSAGES = 12
# (feedback documents, feedback terms, weight): from gentle to strong, so the metrics show which direction helps
FEEDBACK = {"prf_a": (5, 20, 0.5), "prf_b": (10, 40, 0.5), "prf_c": (5, 20, 1.0)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str) -> Path:
    from huggingface_hub import hf_hub_download

    path = Path(hf_hub_download(DATASET, name, repo_type="dataset", revision=REVISION))
    size, expected = FILES[name]
    if path.stat().st_size != size or sha256(path) != expected:
        raise SystemExit(f"integrity failure for {name}")
    print(f"verified {name}", flush=True)
    return path


def as_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = ast.literal_eval(value)
    return [str(v) for v in value] if isinstance(value, list | tuple) else []


def main() -> int:
    # arguments are constants: a fixed repository URL and a pinned commit, never caller input
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--no-deps", f"git+{REPO}@{COMMIT}"])  # noqa: S603
    import pyarrow.parquet as pq

    from constellation.eval.retrieval import evaluate
    from constellation.retrieval.bm25 import Bm25Index

    started = time.time()
    docs_path, questions_path = fetch("data/documents/test.parquet"), fetch("data/questions/test.parquet")
    questions = pq.read_table(questions_path).to_pylist()
    gold = {q["question_id"]: set(as_list(q["expected_doc_ids"])) for q in questions}
    types = {q["question_id"]: q["question_type"] for q in questions}
    ids: list[str] = []

    def document_batches():  # type: ignore[no-untyped-def]
        for batch in pq.ParquetFile(docs_path).iter_batches(batch_size=4_000, columns=["doc_id", "title", "content"]):
            rows = batch.to_pydict()
            ids.extend(rows["doc_id"])
            yield [f"{t}\n{c[:MAX_CHARS]}" for t, c in zip(rows["title"], rows["content"], strict=True)]

    rankings: dict[str, dict[str, list[str]]] = {}
    index = Bm25Index.build(document_batches())
    print(f"document index built in {time.time() - started:.0f}s", flush=True)
    rankings["bm25"] = {q["question_id"]: [ids[i] for i, _ in index.search(q["question"], k=DEPTH)] for q in questions}
    for name, (n_docs, n_terms, weight) in FEEDBACK.items():
        rankings[name] = {
            q["question_id"]: [
                ids[i]
                for i, _ in index.search_with_feedback(
                    q["question"], k=DEPTH, feedback_docs=n_docs, feedback_terms=n_terms, weight=weight
                )
            ]
            for q in questions
        }
        print(f"{name} done at {time.time() - started:.0f}s", flush=True)
    del index
    gc.collect()

    owner: list[int] = []

    def passage_batches():  # type: ignore[no-untyped-def]
        position = 0
        for batch in pq.ParquetFile(docs_path).iter_batches(batch_size=2_000, columns=["title", "content"]):
            rows = batch.to_pydict()
            out: list[str] = []
            for title, content in zip(rows["title"], rows["content"], strict=True):
                for n in range(MAX_PASSAGES):
                    chunk = content[n * PASSAGE_CHARS : (n + 1) * PASSAGE_CHARS]
                    if n and len(chunk) < 200:
                        break
                    out.append(f"{title}\n{chunk}")
                    owner.append(position)
                position += 1
            yield out

    passages = Bm25Index.build(passage_batches())
    print(f"passage index: {passages.documents} passages built at {time.time() - started:.0f}s", flush=True)
    rankings["bm25_passage"] = {}
    for q in questions:
        # a document ranks where its best passage ranks
        seen = dict.fromkeys(owner[i] for i, _ in passages.search(q["question"], k=4_000))
        rankings["bm25_passage"][q["question_id"]] = [ids[d] for d in list(seen)[:DEPTH]]

    result = {
        "commit": COMMIT,
        "dataset_revision": REVISION,
        "documents": len(ids),
        "passages": len(owner),
        "feedback_configs": {k: {"docs": v[0], "terms": v[1], "weight": v[2]} for k, v in FEEDBACK.items()},
        "total_seconds": round(time.time() - started),
        "systems": {name: evaluate(r, gold, types, ks=KS) for name, r in rankings.items()},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (OUT / "rankings.json").write_text(json.dumps(rankings) + "\n")
    for name, metrics in result["systems"].items():
        print(name, {k: metrics[k] for k in ("mrr", "hit@1", "hit@10", "hit@100", "hit@200")}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
