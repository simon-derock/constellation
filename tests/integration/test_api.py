import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from falkordb import FalkorDB
from fastapi.testclient import TestClient

from constellation.agents.llm import LLMError, Reply, Usage
from constellation.api.app import Settings, Tenant, create_app
from constellation.graph.read import ReadPort
from constellation.ingest.build_apex import build
from constellation.memory.store import MemoryStore

pytestmark = pytest.mark.integration
GRAPH = "brain:apex-api"
ORIGIN = "https://constellation.example.org"


class Scripted:
    def __init__(self, replies: list[str]) -> None:
        self.replies, self.calls = replies, 0
        self.usage: list[Usage] = []

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        self.calls += 1
        self.usage.append(Usage(prompt_tokens=120, completion_tokens=30, latency_ms=1.0))
        body = self.replies.pop(0)
        return Reply(body, (), {"role": "assistant", "content": body})


PLAN = json.dumps(
    {"day": 8, "event_type": "incident_opened", "people": ["Jax"], "target_type": "sf_deals_risk_flagged"}
)
PICK = json.dumps({"event": "EVT-8-incident_opened-1219"})


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB) -> ReadPort:
    if not Path("data/raw/apex").exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, Path("data/raw/apex"), Path("pins/datasets.json"))
    return ReadPort(falkordb)


def make_client(port: ReadPort, tmp_path: Path, llm: Scripted | None = None, asks_per_minute: int = 30) -> TestClient:
    roles = {"Alex": "engineering_mobile", "Tom": "hr_ops"}
    settings = Settings(
        tenants={"apex": Tenant("apex", GRAPH, "Apex Athletics", roles)},
        allowed_origins=(ORIGIN,),
        published=tmp_path,
        asks_per_minute=asks_per_minute,
        asks_per_day=1_000,
    )
    scripted = llm or Scripted([PLAN, PICK, PICK])
    return TestClient(create_app(port, settings, llm_factory=lambda: scripted))


def test_health_and_readiness(port: ReadPort, tmp_path: Path) -> None:
    client = make_client(port, tmp_path)
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["tenants"]["apex"] > 10_000


def test_every_response_carries_security_headers(port: ReadPort, tmp_path: Path) -> None:
    headers = make_client(port, tmp_path).get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


def test_cors_admits_only_the_configured_origin(port: ReadPort, tmp_path: Path) -> None:
    client = make_client(port, tmp_path)
    ok = client.options("/api/v1/ask", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
    bad = client.options(
        "/api/v1/ask", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert ok.headers.get("access-control-allow-origin") == ORIGIN
    assert "access-control-allow-origin" not in bad.headers


@pytest.mark.ac("AC-INV-03")
def test_an_answer_carries_a_proof_that_replays(port: ReadPort, tmp_path: Path) -> None:
    client = make_client(port, tmp_path)
    body = {
        "tenant": "apex",
        "kind": "SILENCE",
        "question": "Was a risk flag raised after the Day 8 incident with Jax?",
    }
    got = client.post("/api/v1/ask", json=body)
    assert got.status_code == 200, got.text
    data = got.json()
    assert data["answer"]["exists"] is False
    assert data["proof"]["queries"]
    assert data["trace"]["llm_calls"] == 1
    assert data["trace"]["prompt_tokens"] == 120
    replayed = client.post("/api/v1/replay", json={"tenant": "apex", "queries": data["proof"]["queries"]})
    assert replayed.status_code == 200
    assert replayed.json()["all_match"] is True


@pytest.mark.ac("AC-INV-03")
def test_a_tampered_proof_fails_replay(port: ReadPort, tmp_path: Path) -> None:
    client = make_client(port, tmp_path)
    queries = [{"name": "event_types", "params": {}, "sha256": "0" * 64}]
    out = client.post("/api/v1/replay", json={"tenant": "apex", "queries": queries})
    assert out.status_code == 200
    assert out.json()["all_match"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"tenant": "nope", "kind": "SILENCE", "question": "q"},
        {"tenant": "apex", "kind": "OTHER", "question": "q"},
        {"tenant": "apex", "kind": "SILENCE", "question": "x" * 601},
        {"tenant": "apex", "kind": "SILENCE", "question": ""},
        {"tenant": "apex", "kind": "PERSPECTIVE", "question": "q"},
        {"tenant": "apex", "kind": "PERSPECTIVE", "question": "q", "actor": "Alex", "day": 10_000},
        {"tenant": "apex", "kind": "PERSPECTIVE", "question": "q", "actor": "Stranger", "day": 5},
    ],
)
def test_invalid_questions_are_refused_before_any_model_call(
    port: ReadPort, tmp_path: Path, body: dict[str, Any]
) -> None:
    llm = Scripted([])
    client = make_client(port, tmp_path, llm)
    assert client.post("/api/v1/ask", json=body).status_code == 422
    assert llm.calls == 0


def test_the_rate_limit_stops_a_caller_before_the_model_is_touched(port: ReadPort, tmp_path: Path) -> None:
    llm = Scripted([PLAN, PLAN, PLAN])
    client = make_client(port, tmp_path, llm, asks_per_minute=2)
    body = {"tenant": "apex", "kind": "SILENCE", "question": "Was a risk flag raised after the Day 8 incident?"}
    assert [client.post("/api/v1/ask", json=body).status_code for _ in range(3)] == [200, 200, 429]
    assert llm.calls == 2


def test_the_scoreboard_lists_published_runs_only(port: ReadPort, tmp_path: Path) -> None:
    (tmp_path / "epistemic-test.summary.json").write_text(json.dumps({"questions": 78, "combined_score": 0.5}))
    (tmp_path / "ignored.txt").write_text("no")
    runs = make_client(port, tmp_path).get("/api/v1/scoreboard").json()["runs"]
    assert [r["questions"] for r in runs] == [78]


def test_the_mcp_server_is_mounted_beside_the_api(port: ReadPort, tmp_path: Path) -> None:
    app = create_app(
        port,
        Settings(tenants={"apex": Tenant("apex", GRAPH, "Apex", {})}, allowed_origins=(), published=tmp_path),
        llm_factory=lambda: Scripted([]),
    )
    assert "/mcp" in {getattr(r, "path", "") for r in app.routes}


class Failing:
    def __init__(self) -> None:
        self.usage: list[Usage] = []

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        raise LLMError("@cf/openai/gpt-oss-20b failed with HTTP 429: daily allocation used up")


def test_an_unavailable_model_is_a_clean_503_that_leaks_no_detail(port: ReadPort, tmp_path: Path) -> None:
    settings = Settings(
        tenants={"apex": Tenant("apex", GRAPH, "Apex", {})}, allowed_origins=(), published=tmp_path, asks_per_minute=9
    )
    client = TestClient(create_app(port, settings, llm_factory=Failing))
    body = {"tenant": "apex", "kind": "SILENCE", "question": "Was a postmortem written?"}
    out = client.post("/api/v1/ask", json=body)
    assert out.status_code == 503
    assert out.json() == {"detail": "the model is unavailable right now; recorded runs are still browsable"}


@pytest.mark.ac("AC-T3-02")
def test_the_ownership_timeline_lists_every_domain_with_a_replayable_proof(port: ReadPort, tmp_path: Path) -> None:
    client = make_client(port, tmp_path)
    body = client.get("/api/v1/ownership", params={"tenant": "apex"}).json()
    domains = {d["domain"]: d["intervals"] for d in body["domains"]}
    assert len(domains) == 10
    titan = domains["Project Titan"]
    assert [i["owner"] for i in titan] == ["Bill", "Sharon", "Sam"]
    assert titan[-1]["to"] is None
    assert titan[-1]["origin"] == "claim"
    replayed = client.post("/api/v1/replay", json={"tenant": "apex", "queries": body["proof"]["queries"]})
    assert replayed.json()["all_match"] is True


def test_actors_come_from_the_server_side_role_table(port: ReadPort, tmp_path: Path) -> None:
    client = make_client(port, tmp_path)
    actors = client.get("/api/v1/actors", params={"tenant": "apex"}).json()["actors"]
    assert actors == [{"name": "Alex", "role": "engineering_mobile"}, {"name": "Tom", "role": "hr_ops"}]
    assert client.get("/api/v1/actors", params={"tenant": "nope"}).status_code == 422
    assert client.get("/api/v1/ownership", params={"tenant": "nope"}).status_code == 422


class FakeIssues:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, action: Any) -> dict[str, object]:
        self.calls += 1
        return {"dry_run": False, "url": "https://github.com/o/r/issues/9", "number": 9}


def act_client(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, approver_key: str = "s3cret", sink: FakeIssues | None = None
) -> TestClient:
    settings = Settings(
        tenants={"apex": Tenant("apex", GRAPH, "Apex", {})},
        allowed_origins=(),
        published=tmp_path,
        approver_key=approver_key,
        real_actions_per_day=1,
    )
    memory = MemoryStore(falkordb, f"api{uuid.uuid4().hex[:6]}")
    return TestClient(
        create_app(port, settings, llm_factory=lambda: Scripted([]), memory=memory, real_sink=sink, repo="o/r")
    )


def first_suggestion(client: TestClient) -> dict[str, Any]:
    found = client.get("/api/v1/actions/suggestions", params={"tenant": "apex"}).json()["suggestions"]
    return next(s for s in found if "kubernetes-deploy" in s["title"])


@pytest.mark.ac("AC-T1-04")
def test_suggestions_come_from_the_ownership_graph_with_their_evidence(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    client = act_client(port, falkordb, tmp_path)
    suggestion = first_suggestion(client)
    assert "day 34" in suggestion["body"]
    assert suggestion["evidence"][0]["name"] == "ownership_all"
    assert len(suggestion["payload_hash"]) == 64


@pytest.mark.ac("AC-INV-05")
def test_only_a_server_derived_suggestion_can_be_proposed(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> None:
    client = act_client(port, falkordb, tmp_path)
    forged = client.post("/api/v1/actions", json={"tenant": "apex", "payload_hash": "f" * 64})
    assert forged.status_code == 422
    suggestion = first_suggestion(client)
    made = client.post("/api/v1/actions", json={"tenant": "apex", "payload_hash": suggestion["payload_hash"]})
    assert made.status_code == 200
    assert made.json()["status"] == "proposed"
    assert client.get("/api/v1/actions").json()["actions"][0]["id"] == made.json()["id"]


@pytest.mark.ac("AC-INV-05")
def test_anyone_may_approve_a_dry_run_and_it_changes_nothing_real(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    sink = FakeIssues()
    client = act_client(port, falkordb, tmp_path, sink=sink)
    action_id = client.post(
        "/api/v1/actions", json={"tenant": "apex", "payload_hash": first_suggestion(client)["payload_hash"]}
    ).json()["id"]
    done = client.post(f"/api/v1/actions/{action_id}/approve", json={"mode": "dry-run"}).json()
    assert (done["status"], done["mode"]) == ("executed", "dry-run")
    assert done["result"]["dry_run"] is True
    assert sink.calls == 0
    assert client.post(f"/api/v1/actions/{action_id}/approve", json={"mode": "dry-run"}).status_code == 409


@pytest.mark.ac("AC-INV-05")
def test_real_execution_needs_the_operator_key_and_a_configured_sink(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    sink = FakeIssues()
    client = act_client(port, falkordb, tmp_path, sink=sink)
    payload = first_suggestion(client)["payload_hash"]
    action_id = client.post("/api/v1/actions", json={"tenant": "apex", "payload_hash": payload}).json()["id"]
    url = f"/api/v1/actions/{action_id}/approve"
    assert client.post(url, json={"mode": "real"}).status_code == 403
    assert client.post(url, json={"mode": "real"}, headers={"X-Approver-Key": "wrong"}).status_code == 403
    assert sink.calls == 0
    done = client.post(url, json={"mode": "real"}, headers={"X-Approver-Key": "s3cret"}).json()
    assert (done["status"], done["approver"]) == ("executed", "operator")
    assert done["result"]["url"] == "https://github.com/o/r/issues/9"
    assert sink.calls == 1


def test_real_execution_is_unavailable_when_no_sink_is_configured(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    client = act_client(port, falkordb, tmp_path, sink=None)
    action_id = client.post(
        "/api/v1/actions", json={"tenant": "apex", "payload_hash": first_suggestion(client)["payload_hash"]}
    ).json()["id"]
    out = client.post(
        f"/api/v1/actions/{action_id}/approve", json={"mode": "real"}, headers={"X-Approver-Key": "s3cret"}
    )
    assert out.status_code == 503


def test_an_unset_operator_key_disables_real_execution_entirely(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    client = act_client(port, falkordb, tmp_path, approver_key="", sink=FakeIssues())
    action_id = client.post(
        "/api/v1/actions", json={"tenant": "apex", "payload_hash": first_suggestion(client)["payload_hash"]}
    ).json()["id"]
    out = client.post(f"/api/v1/actions/{action_id}/approve", json={"mode": "real"}, headers={"X-Approver-Key": ""})
    assert out.status_code == 403


def test_the_daily_cap_on_real_actions_is_a_429(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> None:
    client = act_client(port, falkordb, tmp_path, sink=FakeIssues())
    found = client.get("/api/v1/actions/suggestions", params={"tenant": "apex"}).json()["suggestions"]
    assert len(found) >= 2
    codes = []
    for suggestion in found[:2]:
        action_id = client.post(
            "/api/v1/actions", json={"tenant": "apex", "payload_hash": suggestion["payload_hash"]}
        ).json()["id"]
        out = client.post(
            f"/api/v1/actions/{action_id}/approve", json={"mode": "real"}, headers={"X-Approver-Key": "s3cret"}
        )
        codes.append(out.status_code)
    assert codes == [200, 429]
