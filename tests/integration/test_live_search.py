from typing import Any

import pytest
from falkordb import FalkorDB

from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.live.graph import LiveGraph
from constellation.live.model import Item, item_from_github, plan_changes
from constellation.proof import ProofQuery, replay

pytestmark = pytest.mark.integration
GRAPH = "brain:live-search"
KEY = "k" * 32
T1 = 1_770_000_000


def parsed(repo: str, number: int, login: str, title: str) -> Item:
    raw: dict[str, Any] = {
        "number": number,
        "title": title,
        "state": "open",
        "user": {"login": login, "type": "User"},
        "assignees": [],
        "labels": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "closed_at": None,
    }
    item = item_from_github(repo, raw, KEY)
    assert item is not None
    return item


ITEMS = [
    parsed("o/a", 1, "alice", "Vector index crashes on restart"),
    parsed("o/a", 2, "bob", "Graph copy hangs under memory pressure"),
    parsed("o/b", 3, "bob", "Vector search returns stale results"),
    parsed("o/b", 4, "carol", "Document the replication protocol"),
    parsed("o/c", 5, "carol", "Replication lag after failover"),
    parsed("o/d", 6, "dave", "Unrelated benchmark harness cleanup"),
]
VECTORS = {
    "o/a#1": [1.0, 0.0, 0.0, 0.0],
    "o/a#2": [0.0, 1.0, 0.0, 0.0],
    "o/b#3": [0.9, 0.1, 0.0, 0.0],
    "o/b#4": [0.0, 0.0, 1.0, 0.0],
    "o/c#5": [0.0, 0.1, 0.9, 0.0],
    "o/d#6": [0.0, 0.0, 0.0, 1.0],
}


@pytest.fixture
def live(falkordb: FalkorDB) -> LiveGraph:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    graph = LiveGraph(falkordb, WritePort(falkordb), GRAPH)
    for repo in ("o/a", "o/b", "o/c", "o/d"):
        batch = [i for i in ITEMS if i.repo == repo]
        graph.apply(batch, plan_changes({}, batch, observed_at=T1))
    graph.ensure_search_indexes(dim=4)
    graph.set_embeddings([(i.doc_id, i.title, VECTORS[i.doc_id]) for i in ITEMS])
    graph.build_collaboration()
    return graph


def run(falkordb: FalkorDB, name: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    return [list(r) for r in ReadPort(falkordb).run(GRAPH, cypher(name), params or {}).rows]


def test_every_item_is_tied_to_its_repository_and_every_author_to_the_repositories_they_work_in(
    live: LiveGraph,
) -> None:
    assert live.query("MATCH (:Item)-[:IN_REPO]->(r:Repo) RETURN count(DISTINCT r)") == [[4]]
    rows = live.query("MATCH (p:Person)-[:ACTIVE_IN]->(r:Repo) RETURN count(*)")
    assert rows == [[6]]


def test_people_who_share_a_repository_are_linked_in_both_directions_with_the_count(live: LiveGraph) -> None:
    rows = live.query("MATCH (a:Person)-[c:COLLABORATES]->(b:Person) RETURN count(*), max(c.repos)")
    # bob works with alice (o/a) and with carol (o/b); alice and carol share nothing; dave is alone
    assert rows == [[4, 1]]


def test_building_collaboration_twice_changes_nothing(live: LiveGraph) -> None:
    before = live.query("MATCH ()-[c:COLLABORATES]->() RETURN count(c)")
    live.build_collaboration()
    assert live.query("MATCH ()-[c:COLLABORATES]->() RETURN count(c)") == before


def test_the_vector_index_returns_the_nearest_items_first(falkordb: FalkorDB, live: LiveGraph) -> None:
    rows = run(falkordb, "live_search_vector", {"vector": [1.0, 0.0, 0.0, 0.0], "k": 3})
    assert [r[0] for r in rows][:2] == ["o/a#1", "o/b#3"]
    distances = [r[3] for r in rows]
    assert distances == sorted(distances)


def test_the_full_text_index_finds_titles_by_word(falkordb: FalkorDB, live: LiveGraph) -> None:
    rows = run(falkordb, "live_search_text", {"query": "replication", "limit": 5})
    assert {r[0] for r in rows} == {"o/b#4", "o/c#5"}


def test_ensuring_the_indexes_twice_is_not_an_error(live: LiveGraph) -> None:
    live.ensure_search_indexes(dim=4)


def test_changing_a_title_marks_the_embedding_stale_until_it_is_recomputed(live: LiveGraph) -> None:
    assert live.pending_embeddings(10) == []
    renamed = parsed("o/d", 6, "dave", "Benchmark harness rewritten")
    live.apply([renamed], plan_changes(live.open_claims("o/d"), [renamed], observed_at=T1))
    assert [i for i, _ in live.pending_embeddings(10)] == ["o/d#6"]
    live.set_embeddings([("o/d#6", renamed.title, VECTORS["o/d#6"])])
    assert live.pending_embeddings(10) == []


def test_central_people_are_ranked_and_the_bridge_scores_highest_for_the_connector(
    falkordb: FalkorDB, live: LiveGraph
) -> None:
    ranks = run(falkordb, "live_central_people", {"limit": 10})
    assert [r[1] for r in ranks] == sorted((r[1] for r in ranks), reverse=True)
    bridges = run(falkordb, "live_bridge_people", {"limit": 10})
    # the author of o/a#2 and o/b#3 is the only person on a shortest path between two others
    assert bridges[0][0] == ITEMS[1].author
    assert bridges[0][1] > 0


def test_the_shortest_collaboration_path_runs_through_the_connector(falkordb: FalkorDB, live: LiveGraph) -> None:
    alice = ITEMS[0].author
    carol = ITEMS[3].author
    rows = run(falkordb, "live_path", {"from": alice, "to": carol})
    assert rows[0][1] == 2
    assert rows[0][0][0] == alice
    assert rows[0][0][-1] == carol
    assert len(rows[0][0]) == 3


def test_components_report_the_isolated_person_separately(falkordb: FalkorDB, live: LiveGraph) -> None:
    rows = run(falkordb, "live_components")
    assert sorted(rows) == [[1, 1], [3, 1]]


def test_algorithm_answers_are_deterministic_so_they_can_be_proven(falkordb: FalkorDB, live: LiveGraph) -> None:
    port = ReadPort(falkordb)
    for name, params in (("live_central_people", {"limit": 10}), ("live_bridge_people", {"limit": 10})):
        a = port.run(GRAPH, cypher(name), params).sha256
        b = port.run(GRAPH, cypher(name), params).sha256
        assert a == b, name


def test_a_vector_search_proof_replays_with_its_embedding_as_a_parameter(falkordb: FalkorDB, live: LiveGraph) -> None:
    port = ReadPort(falkordb)
    params = {"vector": [1.0, 0.0, 0.0, 0.0], "k": 3}
    got = port.run(GRAPH, cypher("live_search_vector"), params)
    assert replay(port, GRAPH, [ProofQuery("live_search_vector", params, got.sha256)]).all_match


def test_legacy_items_loaded_without_repository_edges_can_be_backfilled(falkordb: FalkorDB, live: LiveGraph) -> None:
    falkordb.select_graph(GRAPH).query("MATCH ()-[e:IN_REPO]->() DELETE e")
    assert live.query("MATCH (:Item)-[:IN_REPO]->() RETURN count(*)") == [[0]]
    live.backfill_repos()
    assert live.query("MATCH (:Item)-[:IN_REPO]->(r:Repo) RETURN count(DISTINCT r)") == [[4]]
