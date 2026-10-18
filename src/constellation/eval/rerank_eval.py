import argparse
import ast
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from constellation.eval.retrieval import evaluate
from constellation.retrieval.passages import best_windows

KS = (1, 5, 10, 20, 50, 100)


class Reranker(Protocol):
    def rerank(self, query: str, docs: Sequence[tuple[str, str]], top_n: int) -> list[tuple[str, float]]: ...


def rerank_rankings(
    candidates: Mapping[str, Sequence[str]],
    questions: Mapping[str, str],
    texts: Mapping[str, str],
    reranker: Reranker,
    depth: int,
    only: Sequence[str] | None = None,
    on_done: Callable[[str], None] | None = None,
) -> dict[str, list[str]]:
    # the reranker sees only the top `depth` candidates of each question; what it was not shown cannot be ranked, so
    # the candidate recall at that depth is the ceiling of the result
    wanted = [q for q in candidates if only is None or q in only]
    out: dict[str, list[str]] = {}
    for qid in wanted:
        ids = list(candidates[qid][:depth])
        docs = [(i, texts[i]) for i in ids]
        out[qid] = [i for i, _ in reranker.rerank(questions[qid], docs, top_n=len(docs))]
        if on_done is not None:
            on_done(qid)
    return out


def rerank_passage_rankings(
    candidates: Mapping[str, Sequence[str]],
    questions: Mapping[str, str],
    texts: Mapping[str, str],
    reranker: Reranker,
    depth: int,
    per_doc: int,
    only: Sequence[str] | None = None,
    on_done: Callable[[str], None] | None = None,
) -> dict[str, list[str]]:
    # each candidate is shown to the reranker as its head plus its most query-specific windows; a document ranks where
    # its best passage ranks, so a long thread is judged by the part that answers, not by its first few paragraphs
    wanted = [q for q in candidates if only is None or q in only]
    out: dict[str, list[str]] = {}
    for qid in wanted:
        ids = list(candidates[qid][:depth])
        chosen = best_windows(questions[qid], {i: texts[i] for i in ids}, per_doc)
        passages = [(f"{i}\x00{n}", w) for i in ids for n, w in enumerate(chosen[i])]
        ranked = reranker.rerank(questions[qid], passages, top_n=len(passages))
        seen = dict.fromkeys(pid.split("\x00")[0] for pid, _ in ranked)
        out[qid] = list(seen)
        if on_done is not None:
            on_done(qid)
    return out


def _list(value: object) -> list[str]:
    parsed = ast.literal_eval(value) if isinstance(value, str) else value
    return [str(v) for v in parsed] if isinstance(parsed, list | tuple) else []


def main() -> int:
    # batch only: reads the pinned parquet files with polars, which the API runtime never imports
    import polars as pl

    from constellation.retrieval.rerank import CohereReranker

    parser = argparse.ArgumentParser(description="Rerank Redwood candidates with Cohere and score them")
    parser.add_argument("--candidates", type=Path, required=True, help="rankings.json from the Kaggle kernel")
    parser.add_argument("--source", default="fused", help="which candidate list to rerank")
    parser.add_argument("--data", type=Path, required=True, help="directory holding data/questions and data/documents")
    parser.add_argument("--depth", type=int, default=100)
    parser.add_argument("--model", default="rerank-v4.0-pro")
    parser.add_argument("--key-env", default="COHERE_API_KEY", help="name of the environment variable holding the key")
    parser.add_argument("--doc-chars", type=int, default=6_000)
    parser.add_argument("--passages-per-doc", type=int, default=0, help="0 reranks document heads; N reranks N windows")
    parser.add_argument("--limit", type=int, default=0, help="rerank only the first N scored questions (smoke runs)")
    parser.add_argument("--cache", type=Path, default=Path("results/cache/rerank"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get(args.key_env) or os.environ.get("COHERE_API_KEY") or os.environ.get("COHERENCE_API_KEY", "")
    if not key:
        raise SystemExit(f"{args.key_env} is required")

    rankings = json.loads(args.candidates.read_text())
    questions = pl.read_parquet(args.data / "data/questions/test.parquet").to_dicts()
    gold = {q["question_id"]: set(_list(q["expected_doc_ids"])) for q in questions}
    types = {q["question_id"]: q["question_type"] for q in questions}
    text_of_question = {q["question_id"]: q["question"] for q in questions}
    scored = [q for q in rankings[args.source] if gold.get(q)]
    if args.limit:
        scored = scored[: args.limit]
    candidates = {q: rankings[args.source][q] for q in scored}
    needed = sorted({d for ids in candidates.values() for d in ids[: args.depth]})
    frame = (
        pl.scan_parquet(args.data / "data/documents/test.parquet")
        .filter(pl.col("doc_id").is_in(needed))
        .select("doc_id", "title", "content")
        .collect()
    )
    # passage mode needs the whole document to find the windows; head mode only its first characters
    limit = 40_000 if args.passages_per_doc else args.doc_chars
    texts = {r["doc_id"]: f"{r['title']}\n{r['content'][:limit]}" for r in frame.to_dicts()}
    reranker = CohereReranker(key, model=args.model, cache_dir=args.cache)
    done = 0

    def progress(_: str) -> None:
        nonlocal done
        done += 1
        if done % 20 == 0 or done == len(candidates):
            print(f"reranked {done}/{len(candidates)}", flush=True)

    if args.passages_per_doc:
        reranked = rerank_passage_rankings(
            candidates, text_of_question, texts, reranker, args.depth, args.passages_per_doc, on_done=progress
        )
    else:
        reranked = rerank_rankings(candidates, text_of_question, texts, reranker, args.depth, on_done=progress)
    subset = {q: gold[q] for q in candidates}
    before = {q: list(candidates[q][: args.depth]) for q in candidates}
    result = {
        "model": args.model,
        "source": args.source,
        "depth": args.depth,
        "doc_chars": args.doc_chars,
        "passages_per_doc": args.passages_per_doc,
        "questions_reranked": len(candidates),
        "before": evaluate(before, subset, types, ks=KS),
        "after": evaluate(reranked, subset, types, ks=KS),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    for name in ("before", "after"):
        m = result[name]
        print(name, {k: m[k] for k in ("mrr", "hit@1", "hit@5", "hit@10", "hit@20")}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
