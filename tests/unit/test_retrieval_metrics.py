import pytest

from constellation.eval.retrieval import evaluate, hit_at, mrr, recall_at

RANKED = ["d1", "d2", "d3", "d4", "d5"]


def test_recall_is_the_share_of_gold_documents_in_the_top_k() -> None:
    assert recall_at(RANKED, {"d2", "d9"}, 3) == 0.5
    assert recall_at(RANKED, {"d2", "d9"}, 1) == 0.0
    assert recall_at(RANKED, {"d1", "d2"}, 5) == 1.0


def test_hit_asks_only_whether_any_gold_document_made_the_cut() -> None:
    assert hit_at(RANKED, {"d3", "d9"}, 3) is True
    assert hit_at(RANKED, {"d3", "d9"}, 2) is False


def test_mrr_uses_the_best_ranked_gold_document() -> None:
    assert mrr(RANKED, {"d3", "d5"}) == pytest.approx(1 / 3)
    assert mrr(RANKED, {"d9"}) == 0.0


def test_duplicate_ranked_ids_do_not_inflate_recall() -> None:
    assert recall_at(["d1", "d1", "d1"], {"d1", "d2"}, 3) == 0.5


def test_questions_with_no_gold_documents_are_counted_but_never_scored() -> None:
    rankings = {"q1": RANKED, "q2": RANKED, "q3": RANKED}
    gold = {"q1": {"d1"}, "q2": {"d9"}, "q3": set()}
    types = {"q1": "basic", "q2": "basic", "q3": "info_not_found"}
    out = evaluate(rankings, gold, types, ks=(1, 5))
    assert out["questions"] == 3
    assert out["scored"] == 2
    assert out["unanswerable"] == 1
    assert out["hit@1"] == 0.5
    assert out["recall@5"] == 0.5
    assert out["by_type"]["basic"]["hit@5"] == 0.5
    assert "info_not_found" not in out["by_type"]


def test_a_missing_ranking_scores_zero_rather_than_disappearing() -> None:
    out = evaluate({}, {"q1": {"d1"}}, {"q1": "basic"}, ks=(10,))
    assert out["hit@10"] == 0.0
    assert out["scored"] == 1
