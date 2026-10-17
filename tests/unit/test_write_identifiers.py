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


def test_control_characters_never_reach_the_graph() -> None:
    from constellation.graph.write import clean

    rows = [{"summary": "synth\x00 repaired", "tags": ["a\x07b"], "n": 3, "ok": "line\nbreak\ttab"}]
    assert clean(rows) == [{"summary": "synth repaired", "tags": ["ab"], "n": 3, "ok": "line\nbreak\ttab"}]
