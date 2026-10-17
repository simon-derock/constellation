import pytest

from constellation.graph.read import canonical_sha256


def test_map_key_order_does_not_change_the_hash() -> None:
    assert canonical_sha256(("m",), [({"a": 1, "b": 2},)]) == canonical_sha256(("m",), [({"b": 2, "a": 1},)])


@pytest.mark.parametrize(("left", "right"), [(1, "1"), (1, True), (1, 1.0), (None, ""), ([1, 2], [2, 1])])
def test_distinct_values_hash_differently(left: object, right: object) -> None:
    assert canonical_sha256(("v",), [(left,)]) != canonical_sha256(("v",), [(right,)])


def test_row_order_is_part_of_the_proof() -> None:
    assert canonical_sha256(("v",), [(1,), (2,)]) != canonical_sha256(("v",), [(2,), (1,)])


def test_column_names_are_part_of_the_proof() -> None:
    assert canonical_sha256(("owner",), [("x",)]) != canonical_sha256(("since",), [("x",)])


def test_graph_objects_must_be_projected_to_properties() -> None:
    with pytest.raises(TypeError, match="project"):
        canonical_sha256(("n",), [(object(),)])
