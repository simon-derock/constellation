import pytest

from constellation.retrieval.fusion import reciprocal_rank_fusion


def test_a_document_both_rankers_like_beats_one_only_one_likes() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "d", "e"]])
    assert fused[0] == "c"
    assert set(fused) == {"a", "b", "c", "d", "e"}


def test_the_score_is_the_sum_of_reciprocal_ranks() -> None:
    # a: 1/(60+1) twice; b: 1/(60+2) once. a must win, and by exactly the formula's margin
    assert reciprocal_rank_fusion([["a", "b"], ["a"]]) == ["a", "b"]


def test_ties_break_by_best_rank_then_by_id_so_the_order_is_reproducible() -> None:
    fused = reciprocal_rank_fusion([["x", "y"], ["y", "x"]])
    # x and y tie on score and on best rank; the id decides
    assert fused == ["x", "y"]
    assert reciprocal_rank_fusion([["b"], ["a"]]) == ["a", "b"]


def test_a_document_repeated_inside_one_ranking_counts_once() -> None:
    assert reciprocal_rank_fusion([["a", "a", "a", "b"], ["b"]]) == ["b", "a"]


def test_a_larger_k_flattens_the_advantage_of_the_top_rank() -> None:
    lists = [["a", "b"], ["b", "c", "a"]]
    assert reciprocal_rank_fusion(lists, k=1)[0] == "b"
    assert reciprocal_rank_fusion(lists, k=1_000)[0] == "b"


def test_empty_input_fuses_to_nothing_and_a_nonpositive_k_is_refused() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
    with pytest.raises(ValueError, match="k must be positive"):
        reciprocal_rank_fusion([["a"]], k=0)
