from typing import Any

import pytest
from falkordb import FalkorDB

from constellation.api.catalogue import prove
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.live.graph import LiveGraph
from constellation.live.model import Item, item_from_github, plan_changes
from constellation.proof import ProofQuery, replay

pytestmark = pytest.mark.integration
GRAPH = "brain:live-stale"
KEY = "k" * 32
T1, T2 = 1_770_000_000, 1_770_000_600


def parsed(state: str = "open") -> Item:
    raw: dict[str, Any] = {
        "number": 1,
        "title": "t",
        "state": state,
        "user": {"login": "alice", "type": "User"},
        "assignees": [],
        "labels": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "closed_at": "2026-01-02T00:00:00Z" if state == "closed" else None,
    }
    item = item_from_github("o/a", raw, KEY)
    assert item is not None
    return item


@pytest.mark.ac("AC-T3-05")
def test_a_change_in_the_source_makes_earlier_answers_replay_as_stale_and_a_fresh_proof_matches(
    falkordb: FalkorDB,
) -> None:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    live = LiveGraph(falkordb, WritePort(falkordb), GRAPH)
    port = ReadPort(falkordb)
    first = parsed()
    live.apply([first], plan_changes({}, [first], observed_at=T1))
    before = prove(port, GRAPH, "live_summary", {})
    pinned = [ProofQuery("live_summary", {}, str(before["sha256"]))]
    assert replay(port, GRAPH, pinned).all_match

    closed = parsed("closed")
    live.apply([closed], plan_changes(live.open_claims("o/a"), [closed], observed_at=T2))

    # the pinned answer is now known to be out of date, and the same question asked again carries a new, matching proof
    assert not replay(port, GRAPH, pinned).all_match
    after = prove(port, GRAPH, "live_summary", {})
    assert after["sha256"] != before["sha256"]
    assert replay(port, GRAPH, [ProofQuery("live_summary", {}, str(after["sha256"]))]).all_match
