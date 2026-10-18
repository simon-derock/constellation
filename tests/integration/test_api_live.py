from typing import Any

import pytest
from falkordb import FalkorDB
from fastapi.testclient import TestClient

from constellation.api.app import Settings, Tenant, create_app
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.live.graph import LiveGraph
from constellation.live.model import item_from_github, plan_changes

pytestmark = pytest.mark.integration
GRAPH = "brain:live-api"
KEY = "k" * 32
OPENED, CLOSED_AT, SYNCED = "2025-12-01T00:00:00Z", "2026-01-10T00:00:00Z", 1_770_000_000
BEFORE_CLOSE, AFTER_CLOSE = 1_767_000_000, 1_769_000_000


def raw(number: int, state: str = "open", login: str = "alice") -> dict[str, Any]:
    return {
        "number": number,
        "title": f"item {number}",
        "state": state,
        "user": {"login": login, "type": "User"},
        "assignees": [],
        "labels": [],
        "created_at": OPENED,
        "updated_at": CLOSED_AT if state == "closed" else OPENED,
        "closed_at": CLOSED_AT if state == "closed" else None,
    }


@pytest.fixture(scope="module")
def client(falkordb: FalkorDB, tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    live = LiveGraph(falkordb, WritePort(falkordb), GRAPH)
    first = [item_from_github("o/a", raw(n), KEY) for n in (1, 2, 3)]
    items = [i for i in first if i is not None]
    live.apply(items, plan_changes({}, items, observed_at=SYNCED))
    live.set_cursor("o/a", OPENED)
    closed = item_from_github("o/a", raw(1, "closed"), KEY)
    assert closed is not None
    live.apply([closed], plan_changes(live.open_claims("o/a"), [closed], observed_at=SYNCED))
    live.set_cursor("o/a", CLOSED_AT)
    settings = Settings(
        tenants={"falkordb": Tenant("falkordb", GRAPH, "FalkorDB (public GitHub)", {}, live=True)},
        allowed_origins=(),
        published=tmp_path_factory.mktemp("published"),
    )
    return TestClient(create_app(ReadPort(falkordb), settings, llm_factory=lambda: pytest.fail("no model needed")))


def states(body: dict[str, Any], key: str) -> dict[str, int]:
    return {f"{r['kind']}:{r['state']}": r["items"] for r in body[key]}


def test_the_live_view_reports_now_and_the_recent_change(client: TestClient) -> None:
    body = client.get("/api/v1/live", params={"tenant": "falkordb"}).json()
    assert states(body, "summary") == {"issue:open": 2, "issue:closed": 1}
    assert [(c["item"], c["old"], c["new"]) for c in body["changes"]] == [("o/a#1", "open", "closed")]
    assert body["freshness"] == {"newest": CLOSED_AT, "repositories": 1}


def test_the_past_can_be_asked_about_and_differs_from_now(client: TestClient) -> None:
    before = client.get("/api/v1/live", params={"tenant": "falkordb", "at": BEFORE_CLOSE}).json()
    after = client.get("/api/v1/live", params={"tenant": "falkordb", "at": AFTER_CLOSE}).json()
    assert states(before, "as_of") == {"issue:open": 3}
    assert states(after, "as_of") == {"issue:open": 2, "issue:closed": 1}


def test_its_proof_replays_to_the_same_hashes(client: TestClient) -> None:
    body = client.get("/api/v1/live", params={"tenant": "falkordb", "at": BEFORE_CLOSE}).json()
    queries = body["proof"]["queries"]
    assert {q["name"] for q in queries} >= {"live_summary", "live_state_as_of", "live_recent_changes"}
    replayed = client.post("/api/v1/replay", json={"tenant": "falkordb", "queries": queries}).json()
    assert replayed["all_match"] is True


def test_an_item_history_shows_the_claim_that_replaced_another(client: TestClient) -> None:
    body = client.get("/api/v1/live/item", params={"tenant": "falkordb", "item": "o/a#1"}).json()
    state = [h for h in body["history"] if h["predicate"] == "state"]
    assert [(h["value"], h["replaced"]) for h in state] == [("open", None), ("closed", "open")]


def test_a_tenant_without_a_live_graph_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/live", params={"tenant": "nope"}).status_code == 422


def test_questions_are_refused_for_a_live_tenant(client: TestClient) -> None:
    body = {"tenant": "falkordb", "kind": "SILENCE", "question": "anything"}
    assert client.post("/api/v1/ask", json=body).status_code == 422


def test_a_malformed_item_id_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/live/item", params={"tenant": "falkordb", "item": "x" * 300}).status_code == 422
