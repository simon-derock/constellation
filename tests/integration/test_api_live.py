from collections.abc import Sequence
from typing import Any

import pytest
from falkordb import FalkorDB
from fastapi.testclient import TestClient

from constellation.api.app import Settings, Tenant, create_app
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.live.embed import Kind
from constellation.live.graph import LiveGraph
from constellation.live.model import item_from_github, plan_changes
from constellation.live.pseudonyms import pseudonym

pytestmark = pytest.mark.integration
GRAPH = "brain:live-api"
KEY = "k" * 32
TITLES = {1: "crash on restart", 2: "replication lag", 3: "doc the protocol", 4: "lag spike", 5: "doc typo"}
OPENED, CLOSED_AT, SYNCED = "2025-12-01T00:00:00Z", "2026-01-10T00:00:00Z", 1_770_000_000
BEFORE_CLOSE, AFTER_CLOSE = 1_767_000_000, 1_769_000_000


class Axes:
    # a stand-in embedder: three words, three axes
    def embed(self, texts: Sequence[str], kind: Kind) -> list[list[float]]:
        words = ("crash", "lag", "doc")
        return [[0.05 + sum(1.0 for w in t.lower().split() if w == words[i]) for i in range(3)] for t in texts]


def raw(number: int, state: str = "open", login: str = "alice") -> dict[str, Any]:
    return {
        "number": number,
        "title": {1: "crash on restart", 2: "replication lag", 3: "doc the protocol", 4: "lag spike", 5: "doc typo"}[
            number
        ],
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
    first = [item_from_github("o/a", raw(n, login="alice" if n < 4 else "bob"), KEY) for n in (1, 2, 3, 4)]
    first += [item_from_github("o/b", raw(5, login="bob"), KEY)]
    items = [i for i in first if i is not None]
    live.apply(items, plan_changes({}, items, observed_at=SYNCED))
    live.ensure_search_indexes(dim=3)
    from constellation.live.search import embed_pending

    embed_pending(live, Axes(), limit=50)
    live.build_collaboration()
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
    app = create_app(ReadPort(falkordb), settings, llm_factory=lambda: pytest.fail("no model needed"), embedder=Axes())
    return TestClient(app)


def states(body: dict[str, Any], key: str) -> dict[str, int]:
    return {f"{r['kind']}:{r['state']}": r["items"] for r in body[key]}


def test_the_live_view_reports_now_and_the_recent_change(client: TestClient) -> None:
    body = client.get("/api/v1/live", params={"tenant": "falkordb"}).json()
    assert states(body, "summary") == {"issue:open": 4, "issue:closed": 1}
    assert [(c["item"], c["old"], c["new"]) for c in body["changes"]] == [("o/a#1", "open", "closed")]
    assert body["freshness"] == {"newest": CLOSED_AT, "repositories": 1}


def test_the_past_can_be_asked_about_and_differs_from_now(client: TestClient) -> None:
    before = client.get("/api/v1/live", params={"tenant": "falkordb", "at": BEFORE_CLOSE}).json()
    after = client.get("/api/v1/live", params={"tenant": "falkordb", "at": AFTER_CLOSE}).json()
    assert states(before, "as_of") == {"issue:open": 5}
    assert states(after, "as_of") == {"issue:open": 4, "issue:closed": 1}


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


ALICE, BOB = pseudonym("alice", KEY), pseudonym("bob", KEY)


def replays(client: TestClient, body: dict[str, Any]) -> bool:
    queries = body["proof"]["queries"]
    return bool(client.post("/api/v1/replay", json={"tenant": "falkordb", "queries": queries}).json()["all_match"])


def test_search_combines_the_vector_and_the_text_index_and_its_proof_replays(client: TestClient) -> None:
    body = client.get("/api/v1/live/search", params={"tenant": "falkordb", "q": "lag"}).json()
    assert body["vector_used"] is True
    assert {h["item"] for h in body["hits"][:2]} >= {"o/a#2", "o/a#4"}
    assert any(set(h["via"]) == {"vector", "text"} for h in body["hits"])
    assert replays(client, body)


def test_a_search_with_nothing_searchable_returns_nothing_rather_than_everything(client: TestClient) -> None:
    body = client.get("/api/v1/live/search", params={"tenant": "falkordb", "q": " ?! "}).json()
    assert body["hits"] == []


def test_an_over_long_search_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/live/search", params={"tenant": "falkordb", "q": "x" * 201}).status_code == 422


def test_people_are_ranked_by_graph_algorithms_and_the_proof_replays(client: TestClient) -> None:
    body = client.get("/api/v1/live/people", params={"tenant": "falkordb"}).json()
    assert {p["person"] for p in body["central"]} == {ALICE, BOB}
    # two people have nobody between them, so neither bridges anything
    assert [b["score"] for b in body["bridges"]] == [0, 0]
    assert body["components"] == [{"size": 2, "components": 1}]
    assert replays(client, body)


def test_the_collaboration_path_names_the_chain_and_refuses_malformed_aliases(client: TestClient) -> None:
    body = client.get("/api/v1/live/path", params={"tenant": "falkordb", "a": ALICE, "b": BOB}).json()
    assert (body["path"], body["hops"]) == ([ALICE, BOB], 1)
    assert replays(client, body)
    assert client.get("/api/v1/live/path", params={"tenant": "falkordb", "a": "A B!", "b": BOB}).status_code == 422
    nobody = client.get("/api/v1/live/path", params={"tenant": "falkordb", "a": ALICE, "b": "no-such-person"}).json()
    assert nobody["path"] == []


def test_the_graph_views_for_a_live_tenant_list_and_draw_from_replayable_queries(client: TestClient) -> None:
    listed = client.get("/api/v1/graph/views").json()["views"]
    assert {v["id"] for v in listed} == {"live-network", "live-repos"}
    body = client.get("/api/v1/graph", params={"view": "live-network"}).json()
    assert body["view"]["tenant"] == "falkordb"
    assert {n["label"] for n in body["nodes"]} == {ALICE, BOB}
    assert [e["relationship_type"] for e in body["edges"]] == ["COLLABORATES"]
    assert replays(client, body)


def test_the_repository_view_ties_people_to_repositories(client: TestClient) -> None:
    body = client.get("/api/v1/graph", params={"view": "live-repos"}).json()
    types = {n["type"] for n in body["nodes"]}
    assert types == {"Person", "Repo"}
    assert replays(client, body)


def test_an_unknown_or_unavailable_view_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/graph", params={"view": "nope"}).status_code == 422
    assert client.get("/api/v1/graph", params={"view": "apex-causal"}).status_code == 422
