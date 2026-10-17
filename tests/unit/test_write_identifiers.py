import pytest

from constellation.graph.write import safe_identifier


@pytest.mark.parametrize("name", ["Person", "doc_id", "Artifact", "row_day", "_hidden"])
def test_plain_identifiers_pass(name: str) -> None:
    assert safe_identifier(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "1abc", "Person) DETACH DELETE (n", "a b", "x`y", "doc-id", "n.prop", "Person;", "名前", "a" * 65],
)
def test_anything_that_could_change_the_query_shape_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        safe_identifier(name)
