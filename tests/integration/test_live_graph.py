from typing import Any

import pytest
from falkordb import FalkorDB

from constellation.graph.write import WritePort
from constellation.live.graph import LiveGraph
from constellation.live.model import Item, item_from_github, plan_changes

pytestmark = pytest.mark.integration
GRAPH = "brain:live-test"
KEY = "k" * 32
T1, T2, T3 = 1_760_100_000, 1_760_200_000, 1_760_300_000


def raw(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "number": 7,
        "title": "fix runtime bounds",
        "state": "open",
        "user": {"login": "gkorland", "type": "User"},
        "assignees": [],
        "labels": [{"name": "bug"}],
        "created_at": "2025-10-09T08:00:00Z",
        "updated_at": "2025-10-09T08:00:00Z",
        "closed_at": None,
    }
    return {**base, **over}


def parsed(**over: Any) -> Item:
    got = item_from_github("FalkorDB/core", raw(**over), KEY)
    assert got is not None
    return got


@pytest.fixture
def live(falkordb: FalkorDB) -> LiveGraph:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    return LiveGraph(falkordb, WritePort(falkordb), GRAPH)


def sync(live: LiveGraph, item: Item, at: int) -> None:
    live.apply([item], plan_changes(live.open_claims("FalkorDB/core"), [item], observed_at=at))


OPEN_STATE = "MATCH (c:Claim {predicate: 'state', value: 'open'}) WHERE c.valid_to IS NULL RETURN count(c)"


def count(live: LiveGraph, cypher: str) -> int:
    return int(live.query(cypher)[0][0])


def test_first_sight_loads_the_item_its_claims_and_its_author(live: LiveGraph) -> None:
    sync(live, parsed(), T1)
    assert count(live, "MATCH (i:Item) RETURN count(i)") == 1
    assert count(live, "MATCH (:Item)-[:AUTHORED_BY]->(:Person) RETURN count(*)") == 1
    assert count(live, OPEN_STATE) == 1


def test_a_replayed_sync_changes_nothing(live: LiveGraph) -> None:
    sync(live, parsed(), T1)
    before = count(live, "MATCH (n) RETURN count(n)")
    sync(live, parsed(), T2)
    assert count(live, "MATCH (n) RETURN count(n)") == before


def test_a_transition_closes_the_old_claim_opens_the_new_one_and_links_them(live: LiveGraph) -> None:
    sync(live, parsed(), T1)
    sync(live, parsed(state="closed", closed_at="2025-10-10T00:00:00Z"), T2)
    rows = live.query(
        "MATCH (n:Claim)-[:SUPERSEDES]->(o:Claim) WHERE n.predicate = 'state' "
        "RETURN o.value, n.value, o.valid_to = n.valid_from"
    )
    assert rows == [["open", "closed", True]]
    assert count(live, "MATCH (c:Change {predicate: 'state'}) RETURN count(c)") == 1


def test_replaying_a_closure_does_not_reopen_the_closed_claim(live: LiveGraph) -> None:
    sync(live, parsed(), T1)
    closed = parsed(state="closed", closed_at="2025-10-10T00:00:00Z")
    plan = plan_changes(live.open_claims("FalkorDB/core"), [closed], observed_at=T2)
    live.apply([closed], plan)
    live.apply([closed], plan)
    assert count(live, OPEN_STATE) == 0


def test_never_more_than_one_open_claim_per_item_and_predicate(live: LiveGraph) -> None:
    sync(live, parsed(), T1)
    sync(live, parsed(labels=[{"name": "bug"}, {"name": "p1"}]), T2)
    sync(live, parsed(labels=[{"name": "p1"}], state="closed", closed_at="2025-10-10T00:00:00Z"), T3)
    violations = live.query(
        "MATCH (i:Item)-[:HAS_CLAIM]->(c:Claim) WHERE c.valid_to IS NULL "
        "WITH i, c.predicate AS p, count(c) AS n WHERE n > 1 RETURN count(*)"
    )
    assert violations == [[0]]


def test_nothing_resembling_a_body_or_a_login_is_stored(live: LiveGraph) -> None:
    sync(live, parsed(body="secret text", assignees=[{"login": "swilly22", "type": "User"}]), T1)
    stored = repr(live.query("MATCH (n) RETURN properties(n)"))
    assert "secret text" not in stored
    assert "gkorland" not in stored
    assert "swilly22" not in stored


def test_the_cursor_round_trips_per_repository(live: LiveGraph) -> None:
    assert live.cursor("FalkorDB/core") is None
    live.set_cursor("FalkorDB/core", "2026-01-01T00:00:00Z")
    live.set_cursor("FalkorDB/core", "2026-02-01T00:00:00Z")
    assert live.cursor("FalkorDB/core") == "2026-02-01T00:00:00Z"
    assert live.cursor("FalkorDB/other") is None
