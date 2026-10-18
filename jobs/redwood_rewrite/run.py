import ast
import gc
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

# Kaggle kernel: an open-weights model rewrites each question into the vocabulary of the documents (a hypothetical
# passage and keywords), and BM25 searches all 511,962 EnterpriseRAG-Bench documents with the original question and with
# each rewrite, alone and fused. It answers one question: does an LLM that restates paraphrased questions lift
# candidate recall where keyword and vector search fail? The package comes from the public repository at COMMIT.
COMMIT = "5f3faadc841a6cff947ee413557f7b301beb672c"
REPO = "https://github.com/simon-derock/constellation"
DATASET = "onyx-dot-app/EnterpriseRAG-Bench"
REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
FILES = {
    "data/documents/test.parquet": (1409893131, "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"),
    "data/questions/test.parquet": (408737, "e25066f4eff3843dd0f3df0d1348113471e072e75007ffe390a0aa83f2a80af2"),
}
OUT = Path("/kaggle/working")
KS = (1, 5, 10, 50, 100, 200)
DEPTH = max(KS)
MAX_CHARS = 40_000
BATCH = 16
NEW_TOKENS = 260


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


def rewrite_all(questions: list[dict]) -> dict[str, str]:  # type: ignore[type-arg]
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from constellation.retrieval.rewrite import build_messages

    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=MODEL_REVISION, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, revision=MODEL_REVISION, dtype=torch.float16, device_map="auto"
    ).eval()
    out: dict[str, str] = {}
    started = time.time()
    for start in range(0, len(questions), BATCH):
        chunk = questions[start : start + BATCH]
        prompts = [
            tokenizer.apply_chat_template(build_messages(q["question"]), tokenize=False, add_generation_prompt=True)
            for q in chunk
        ]
        encoded = tokenizer(prompts, return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            generated = model.generate(**encoded, max_new_tokens=NEW_TOKENS, do_sample=False)
        for q, ids in zip(chunk, generated[:, encoded["input_ids"].shape[1] :], strict=True):
            out[q["question_id"]] = tokenizer.decode(ids, skip_special_tokens=True)
        print(f"rewrote {len(out)}/{len(questions)} in {time.time() - started:.0f}s", flush=True)
        if start == 0:
            print("sample:", json.dumps(list(out.values())[:2])[:900], flush=True)
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return out


def main() -> int:
    # arguments are constants: a fixed repository URL and a pinned commit, never caller input
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--no-deps", f"git+{REPO}@{COMMIT}"])  # noqa: S603
    import pyarrow.parquet as pq

    from constellation.eval.retrieval import evaluate
    from constellation.retrieval.bm25 import Bm25Index
    from constellation.retrieval.fusion import reciprocal_rank_fusion
    from constellation.retrieval.rewrite import parse_rewrite, search_queries

    started = time.time()
    docs_path, questions_path = fetch("data/documents/test.parquet"), fetch("data/questions/test.parquet")
    questions = pq.read_table(questions_path).to_pylist()
    gold = {q["question_id"]: set(as_list(q["expected_doc_ids"])) for q in questions}
    types = {q["question_id"]: q["question_type"] for q in questions}

    raw = rewrite_all(questions)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rewrites.json").write_text(json.dumps(raw) + "\n")
    print(f"rewrites done at {time.time() - started:.0f}s", flush=True)

    ids: list[str] = []

    def batches():  # type: ignore[no-untyped-def]
        for batch in pq.ParquetFile(docs_path).iter_batches(batch_size=4_000, columns=["doc_id", "title", "content"]):
            rows = batch.to_pydict()
            ids.extend(rows["doc_id"])
            yield [f"{t}\n{c[:MAX_CHARS]}" for t, c in zip(rows["title"], rows["content"], strict=True)]

    index = Bm25Index.build(batches())
    print(f"index built at {time.time() - started:.0f}s", flush=True)
    rankings: dict[str, dict[str, list[str]]] = {n: {} for n in ("bm25", "rw_passage", "rw_keywords", "rw_fused")}
    for q in questions:
        qid = q["question_id"]
        lists: dict[str, list[str]] = {}
        for name, text in search_queries(q["question"], parse_rewrite(raw[qid])):
            lists[name] = [ids[i] for i, _ in index.search(text, k=DEPTH)]
        original = lists["original"]
        rankings["bm25"][qid] = original
        rankings["rw_passage"][qid] = lists.get("passage", original)
        rankings["rw_keywords"][qid] = lists.get("keywords", original)
        rankings["rw_fused"][qid] = reciprocal_rank_fusion(list(lists.values()))[:DEPTH]

    result = {
        "commit": COMMIT,
        "dataset_revision": REVISION,
        "model": MODEL,
        "model_revision": MODEL_REVISION,
        "documents": len(ids),
        "total_seconds": round(time.time() - started),
        "systems": {name: evaluate(r, gold, types, ks=KS) for name, r in rankings.items()},
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (OUT / "rankings.json").write_text(json.dumps(rankings) + "\n")
    for name, metrics in result["systems"].items():
        print(name, {k: metrics[k] for k in ("mrr", "hit@1", "hit@10", "hit@100", "hit@200")}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
