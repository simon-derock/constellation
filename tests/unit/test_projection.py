import pytest

from constellation.api.projection import VIEWS, build_graph, view_by_id


def row(s: str, st: str, t: str, tt: str, rel: str) -> tuple[str, str, str, str, str, str, str]:
    return (s, st, s, t, tt, t, rel)


def test_edges_become_typed_nodes_with_a_layer_and_a_degree_weight() -> None:
    nodes, edges = build_graph(
        [row("ann", "Person", "titan", "Domain", "OWNS"), row("bob", "Person", "titan", "Domain", "OWNS")]
    )
    by_id = {n["id"]: n for n in nodes}
    assert set(by_id) == {"Person:ann", "Person:bob", "Domain:titan"}
    assert by_id["Domain:titan"]["weight"] == 2
    assert by_id["Domain:titan"]["layer"] == "product"
    assert by_id["Person:ann"]["layer"] == "identity"
    assert {e["relationship_type"] for e in edges} == {"OWNS"}


def test_the_same_edge_twice_is_one_edge() -> None:
    nodes, edges = build_graph([row("a", "Person", "b", "Person", "X")] * 3)
    assert len(edges) == 1
    assert {n["weight"] for n in nodes} == {1}


def test_an_unknown_node_type_still_draws_with_a_default_layer() -> None:
    nodes, _ = build_graph([row("a", "Widget", "b", "Widget", "X")])
    assert {n["layer"] for n in nodes} == {"intelligence"}


def test_oversized_projections_are_refused_not_silently_truncated() -> None:
    rows = [row(f"p{i}", "Person", f"d{i}", "Domain", "OWNS") for i in range(1_100)]
    with pytest.raises(ValueError, match="too large"):
        build_graph(rows)


def test_every_view_names_catalogue_queries_and_a_known_tenant_kind() -> None:
    from constellation.proof import catalogue_names

    known = catalogue_names()
    for view in VIEWS:
        assert view.tenant in {"apex", "live"}
        assert view.steps, view.id
        for name, _ in view.steps:
            assert name in known, (view.id, name)


def test_view_ids_are_unique_and_lookup_refuses_unknown_ones() -> None:
    assert len({v.id for v in VIEWS}) == len(VIEWS)
    assert view_by_id(VIEWS[0].id) is VIEWS[0]
    with pytest.raises(KeyError):
        view_by_id("no-such-view")
