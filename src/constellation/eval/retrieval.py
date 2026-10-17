from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any


def _top(ranked: Sequence[str], k: int) -> set[str]:
    return set(ranked[:k])


def recall_at(ranked: Sequence[str], gold: set[str], k: int) -> float:
    # a set, so a document ranked twice cannot count twice
    return len(_top(ranked, k) & gold) / len(gold)


def hit_at(ranked: Sequence[str], gold: set[str], k: int) -> bool:
    return bool(_top(ranked, k) & gold)


def mrr(ranked: Sequence[str], gold: set[str]) -> float:
    for position, doc in enumerate(ranked, start=1):
        if doc in gold:
            return 1.0 / position
    return 0.0


def _summary(rows: Sequence[tuple[Sequence[str], set[str]]], ks: Sequence[int]) -> dict[str, float]:
    out: dict[str, float] = {"mrr": round(mean(mrr(r, g) for r, g in rows), 4)}
    for k in ks:
        out[f"hit@{k}"] = round(mean(1.0 if hit_at(r, g, k) else 0.0 for r, g in rows), 4)
        out[f"recall@{k}"] = round(mean(recall_at(r, g, k) for r, g in rows), 4)
    return out


def evaluate(
    rankings: Mapping[str, Sequence[str]],
    gold: Mapping[str, set[str]],
    types: Mapping[str, str],
    ks: Sequence[int] = (1, 5, 10, 50),
) -> dict[str, Any]:
    # questions with no gold documents ("information not found") have nothing to retrieve: counted, never scored
    scored = {q: g for q, g in gold.items() if g}
    rows = {q: (rankings.get(q, []), g) for q, g in scored.items()}
    by_type: dict[str, list[tuple[Sequence[str], set[str]]]] = defaultdict(list)
    for q, row in rows.items():
        by_type[types[q]].append(row)
    return {
        "questions": len(gold),
        "scored": len(scored),
        "unanswerable": len(gold) - len(scored),
        **_summary(list(rows.values()), ks),
        "by_type": {t: {"n": len(r), **_summary(r, ks)} for t, r in sorted(by_type.items())},
    }
