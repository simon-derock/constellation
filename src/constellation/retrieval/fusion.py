from collections.abc import Sequence


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> list[str]:
    # Cormack et al.: a document's score is the sum of 1/(k + rank) over the rankings that contain it, so agreement
    # between rankers outweighs one ranker's confidence, and no score scales need calibrating
    if k <= 0:
        raise ValueError("k must be positive")
    score: dict[str, float] = {}
    best: dict[str, int] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for position, doc in enumerate(ranking, start=1):
            if doc in seen:
                continue
            seen.add(doc)
            score[doc] = score.get(doc, 0.0) + 1.0 / (k + position)
            best[doc] = min(best.get(doc, position), position)
    # ties: higher score, then the better best-rank, then the id, so the same inputs always fuse the same way
    return sorted(score, key=lambda doc: (-score[doc], best[doc], doc))
