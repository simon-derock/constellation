from collections.abc import Sequence

import pytest

from constellation.eval.rerank_eval import rerank_rankings


class Reverse:
    # a stand-in reranker: prefers the document ids that sort last
    def __init__(self) -> None:
        self.queries: list[str] = []

    def rerank(self, query: str, docs: Sequence[tuple[str, str]], top_n: int) -> list[tuple[str, float]]:
        self.queries.append(query)
        ordered = sorted(docs, key=lambda d: d[0], reverse=True)
        return [(i, 1.0 - n / 10) for n, (i, _) in enumerate(ordered)][:top_n]


CANDIDATES = {"q1": ["a", "b", "c", "d"], "q2": ["c", "d"]}
QUESTIONS = {"q1": "first?", "q2": "second?"}
TEXTS = {"a": "A", "b": "B", "c": "C", "d": "D"}


def test_each_question_is_reranked_from_its_own_candidates() -> None:
    got = rerank_rankings(CANDIDATES, QUESTIONS, TEXTS, Reverse(), depth=4)
    assert got == {"q1": ["d", "c", "b", "a"], "q2": ["d", "c"]}


def test_only_the_top_depth_candidates_are_sent_and_the_rest_are_dropped() -> None:
    got = rerank_rankings(CANDIDATES, QUESTIONS, TEXTS, Reverse(), depth=2)
    assert got["q1"] == ["b", "a"]


def test_a_candidate_without_text_is_an_error_not_a_silent_skip() -> None:
    with pytest.raises(KeyError, match="zzz"):
        rerank_rankings({"q": ["a", "zzz"]}, {"q": "?"}, TEXTS, Reverse(), depth=2)


def test_questions_can_be_limited_and_are_visited_in_a_stable_order() -> None:
    reranker = Reverse()
    rerank_rankings(CANDIDATES, QUESTIONS, TEXTS, reranker, depth=4, only=["q2"])
    assert reranker.queries == ["second?"]


def test_progress_is_reported_once_per_question() -> None:
    seen: list[str] = []
    rerank_rankings(CANDIDATES, QUESTIONS, TEXTS, Reverse(), depth=4, on_done=seen.append)
    assert seen == ["q1", "q2"]
