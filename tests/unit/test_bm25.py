import numpy as np
import pytest

from constellation.retrieval.bm25 import Bm25Index

DOCS = [
    "the quarterly billing report was approved by finance",
    "billing billing billing billing billing billing billing billing outage runbook",
    "kubernetes cluster upgrade plan for the platform team and the cluster operators",
    "zebra migration notes",
    "an unrelated note about lunch",
]


def index(docs: list[str] = DOCS) -> Bm25Index:
    return Bm25Index.build([docs[:2], docs[2:]], n_features=2**16)


def test_a_rare_term_ranks_its_document_first() -> None:
    top = index().search("zebra", k=3)
    assert top[0][0] == 3
    assert len(top) == 1


def test_scores_are_descending_and_ties_break_by_document_order() -> None:
    docs = ["alpha beta", "alpha beta", "alpha beta", "gamma"]
    hits = Bm25Index.build([docs], n_features=2**16).search("alpha", k=4)
    assert [i for i, _ in hits] == [0, 1, 2]
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_term_frequency_saturates_instead_of_growing_without_bound() -> None:
    idx = index()
    once = dict(idx.search("billing", k=5))
    # doc 1 repeats the term eight times, doc 0 once: more, but nowhere near eight times more
    assert once[1] > once[0]
    assert once[1] < 3 * once[0]


def test_stopwords_alone_match_nothing() -> None:
    assert index().search("the and of", k=5) == []


def test_k_limits_results_and_indices_refer_to_input_order_across_batches() -> None:
    hits = index().search("cluster", k=1)
    assert hits[0][0] == 2


def test_an_empty_corpus_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        Bm25Index.build([[]], n_features=2**10)


def test_document_count_and_memory_are_reported() -> None:
    idx = index()
    assert idx.documents == 5
    assert idx.nbytes > 0
    assert np.isfinite(idx.avg_length)
