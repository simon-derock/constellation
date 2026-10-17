import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Kaggle kernel: dense retrieval over all 511,962 EnterpriseRAG-Bench documents, fused with BM25 by reciprocal rank
# fusion, scored with the judge-free retrieval metrics. The package comes from the public repository at COMMIT.
COMMIT = "4392144bb4e79b659c4bc76e0b003783638f3b72"
REPO = "https://github.com/simon-derock/constellation"
DATASET = "onyx-dot-app/EnterpriseRAG-Bench"
REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"
MODEL = "BAAI/bge-base-en-v1.5"
MODEL_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
FILES = {
    "data/documents/test.parquet": (1409893131, "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"),
    "data/questions/test.parquet": (408737, "e25066f4eff3843dd0f3df0d1348113471e072e75007ffe390a0aa83f2a80af2"),
}
OUT = Path(os.environ.get("OUT_DIR", "/kaggle/working"))
MAX_DOCS = int(os.environ.get("MAX_DOCS", "0"))
DATA_DIR = os.environ.get("DATA_DIR", "")
KS = (1, 5, 10, 50, 100)
# two passages of about 1,200 characters (roughly 300 tokens) per document: the head, and what follows it
PASSAGE_CHARS = 1_200
PASSAGES = 2
MAX_LENGTH = 320
BATCH = 128


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
    if isinstance(value, str):
        value = ast.literal_eval(value)
    return [str(v) for v in value] if isinstance(value, list | tuple) else []


def passages_of(title: str, content: str) -> list[str]:
    head = f"{title}\n{content[:PASSAGE_CHARS]}"
    out = [head]
    for i in range(1, PASSAGES):
        chunk = content[i * PASSAGE_CHARS : (i + 1) * PASSAGE_CHARS]
        if len(chunk) >= 200:
            out.append(f"{title}\n{chunk}")
    return out


def main() -> int:
    try:
        import constellation  # noqa: F401 — already installed, as in a local smoke run
    except ImportError:
        # arguments are constants: a fixed repository URL and a pinned commit, never caller input
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--no-deps", f"git+{REPO}@{COMMIT}"])  # noqa: S603
    import numpy as np
    import pyarrow.parquet as pq
    import torch
    from transformers import AutoModel, AutoTokenizer

    from constellation.eval.retrieval import evaluate
    from constellation.retrieval.bm25 import Bm25Index
    from constellation.retrieval.fusion import reciprocal_rank_fusion

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and not os.environ.get("ALLOW_CPU"):
        raise SystemExit("no GPU available; this kernel is meant for an accelerator")
    started = time.time()
    docs_path, questions_path = fetch("data/documents/test.parquet"), fetch("data/questions/test.parquet")

    # one pass over the corpus builds both the BM25 index inputs and the passage list
    ids: list[str] = []
    texts: list[str] = []
    owner: list[int] = []
    bm25_batches: list[list[str]] = []
    for batch in pq.ParquetFile(docs_path).iter_batches(batch_size=4_000, columns=["doc_id", "title", "content"]):
        rows = batch.to_pydict()
        bm25_batches.append([f"{t}\n{c[:40_000]}" for t, c in zip(rows["title"], rows["content"], strict=True)])
        for doc_id, title, content in zip(rows["doc_id"], rows["title"], rows["content"], strict=True):
            for passage in passages_of(title, content):
                texts.append(passage)
                owner.append(len(ids))
            ids.append(doc_id)
        if MAX_DOCS and len(ids) >= MAX_DOCS:
            break
    print(f"{len(ids)} documents, {len(texts)} passages prepared in {time.time() - started:.0f}s", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=MODEL_REVISION)
    model = AutoModel.from_pretrained(MODEL, revision=MODEL_REVISION, torch_dtype=torch.float16).to(device).eval()
    dim = model.config.hidden_size

    @torch.no_grad()
    def embed(batch_texts: list[str]) -> torch.Tensor:
        encoded = tokenizer(batch_texts, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
        hidden = model(**{k: v.to(device) for k, v in encoded.items()}).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(hidden.float(), dim=-1).half()

    # longest first: padding waste is smallest when neighbours have similar length
    order = np.argsort([-len(t) for t in texts], kind="stable")
    matrix = torch.empty((len(texts), dim), dtype=torch.float16, device=device)
    embed_started = time.time()
    for done, start in enumerate(range(0, len(texts), BATCH)):
        picked = order[start : start + BATCH]
        matrix[torch.as_tensor(picked, device=device)] = embed([texts[i] for i in picked])
        if done % 200 == 0:
            print(
                f"embedded {start + len(picked)}/{len(texts)} passages in {time.time() - embed_started:.0f}s",
                flush=True,
            )
    embed_seconds = time.time() - embed_started

    questions = pq.read_table(questions_path).to_pylist()
    owner_t = torch.as_tensor(owner, device=device)
    dense: dict[str, list[str]] = {}
    for q in questions:
        query = embed([QUERY_PREFIX + q["question"]])[0]
        scores = matrix @ query
        top = torch.topk(scores.float(), k=min(400, scores.shape[0])).indices
        seen: list[int] = []
        for doc in owner_t[top].tolist():
            if doc not in seen:
                seen.append(doc)
            if len(seen) == max(KS):
                break
        dense[q["question_id"]] = [ids[d] for d in seen]
    print("dense retrieval done", flush=True)

    index = Bm25Index.build(bm25_batches)
    bm25 = {q["question_id"]: [ids[i] for i, _ in index.search(q["question"], k=max(KS))] for q in questions}
    fused = {qid: reciprocal_rank_fusion([bm25[qid], dense[qid]])[: max(KS)] for qid in bm25}

    gold = {q["question_id"]: set(as_list(q["expected_doc_ids"])) for q in questions}
    types = {q["question_id"]: q["question_type"] for q in questions}
    result = {
        "commit": COMMIT,
        "dataset_revision": REVISION,
        "model": MODEL,
        "model_revision": MODEL_REVISION,
        "device": device,
        "max_docs": MAX_DOCS or None,
        "documents": len(ids),
        "passages": len(texts),
        "embed_seconds": round(embed_seconds),
        "total_seconds": round(time.time() - started),
        "systems": {
            "bm25": evaluate(bm25, gold, types, ks=KS),
            "dense": evaluate(dense, gold, types, ks=KS),
            "fused": evaluate(fused, gold, types, ks=KS),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (OUT / "rankings.json").write_text(json.dumps({"dense": dense, "fused": fused}) + "\n")
    for name, metrics in result["systems"].items():
        print(name, {k: metrics[k] for k in ("mrr", "hit@1", "hit@10", "hit@100")}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
