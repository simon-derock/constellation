import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from falkordb import FalkorDB
from fastapi.testclient import TestClient

from constellation.agents.llm import Reply, Usage
from constellation.api.app import Settings, Tenant, create_app
from constellation.graph.read import ReadPort
from constellation.ingest.build_apex import build
from constellation.memory.store import MemoryStore

pytestmark = pytest.mark.integration
GRAPH = "brain:apex-agent-act"
ASK = {"tenant": "apex", "kind": "SILENCE", "question": "Was a risk flag raised after the Day 8 incident with Jax?"}
PLAN = json.dumps(
    {"day": 8, "event_type": "incident_opened", "people": ["Jax"], "target_type": "sf_deals_risk_flagged"}
)


class ScriptedModel:
    # one scripted reply per model call; the planner's calls come first, then the follow-up turn
    def __init__(self, replies: list[Reply]) -> None:
        self.replies, self.calls = replies, 0
        self.tools_offered: list[list[str]] = []
        self.usage: list[Usage] = []

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        self.calls += 1
        self.tools_offered.append([t["function"]["name"] for t in tools])
        self.usage.append(Usage(prompt_tokens=120, completion_tokens=30, latency_ms=1.0))
        return self.replies.pop(0)


def text(body: str) -> Reply:
    return Reply(body, (), {"role": "assistant", "content": body})


def propose(title: str = "Write the postmortem for the Day 8 incident", **over: object) -> Reply:
    args: dict[str, object] = {
        "title": title,
        "body": "No risk flag followed the incident Jax opened on Day 8.",
        "evidence": ["absence"],
        **over,
    }
    tool_call = {"id": "c1", "type": "function", "function": {"name": "propose_action", "arguments": json.dumps(args)}}
    return Reply("", (tool_call,), {"role": "assistant", "content": "", "tool_calls": [tool_call]})


class FakeIssues:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, action: Any) -> dict[str, object]:
        self.calls += 1
        return {"dry_run": False, "url": "https://github.com/o/r/issues/9", "number": 9}


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB) -> ReadPort:
    if not Path("data/raw/apex").exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, Path("data/raw/apex"), Path("pins/datasets.json"))
    return ReadPort(falkordb)


def client_for(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, llm: ScriptedModel, actions: bool = True
) -> tuple[TestClient, FakeIssues]:
    sink = FakeIssues()
    settings = Settings(
        tenants={"apex": Tenant("apex", GRAPH, "Apex", {})},
        allowed_origins=(),
        published=tmp_path,
        asks_per_minute=60,
        asks_per_day=1_000,
        approver_key="s3cret",
        real_actions_per_day=3,
    )
    memory = MemoryStore(falkordb, f"agent{uuid.uuid4().hex[:6]}") if actions else None
    app = create_app(port, settings, llm_factory=lambda: llm, memory=memory, real_sink=sink, repo="o/r")
    return TestClient(app), sink


@pytest.mark.ac("AC-T1-04")
def test_an_answer_can_end_in_one_agent_proposal_whose_evidence_replays(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    llm = ScriptedModel([text(PLAN), propose()])
    client, _sink = client_for(port, falkordb, tmp_path, llm)
    got = client.post("/api/v1/ask", json=ASK)
    assert got.status_code == 200, got.text
    data = got.json()
    action = data["proposed_action"]
    assert (action["provenance"], action["status"], action["kind"]) == ("agent", "proposed", "file_issue")
    assert len(action["payload_hash"]) == 64
    proved = {q["sha256"] for q in data["proof"]["queries"]}
    assert action["evidence"]
    assert {e["sha256"] for e in action["evidence"]} <= proved
    assert all(e["sha256"] in action["body"] for e in action["evidence"])
    assert llm.tools_offered[-1] == ["propose_action"]
    assert "propose_action" not in {t for offered in llm.tools_offered[:-1] for t in offered}
    replayed = client.post("/api/v1/replay", json={"tenant": "apex", "queries": action["evidence"]})
    assert replayed.json()["all_match"] is True
    listed = client.get("/api/v1/actions").json()["actions"]
    assert [(a["id"], a["provenance"]) for a in listed] == [(action["id"], "agent")]


@pytest.mark.ac("AC-T1-05")
def test_the_proposal_is_a_step_in_the_trace_and_a_model_call_in_the_cost(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    client, _sink = client_for(port, falkordb, tmp_path, ScriptedModel([text(PLAN), propose()]))
    trace = client.post("/api/v1/ask", json=ASK).json()["trace"]
    step = trace["tools"][-1]
    assert (step["tool"], step["artifacts"]) == ("propose_action", 1)
    assert trace["llm_calls"] == 2


@pytest.mark.ac("AC-INV-05")
def test_fabricated_evidence_is_refused_and_no_action_exists(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    forged = propose(evidence=["0" * 64])
    client, _sink = client_for(port, falkordb, tmp_path, ScriptedModel([text(PLAN), forged, forged]))
    data = client.post("/api/v1/ask", json=ASK).json()
    assert "proposed_action" not in data
    assert client.get("/api/v1/actions").json()["actions"] == []
    refused = [s for s in data["trace"]["tools"] if s["tool"] == "propose_action"]
    assert [s["artifacts"] for s in refused] == [0, 0]


@pytest.mark.ac("AC-INV-05")
def test_a_reply_with_two_proposals_files_only_the_first(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> None:
    first, second = propose("First proposal"), propose("Second proposal")
    both = Reply("", (*first.tool_calls, *second.tool_calls), first.message)
    client, _sink = client_for(port, falkordb, tmp_path, ScriptedModel([text(PLAN), both]))
    data = client.post("/api/v1/ask", json=ASK).json()
    assert data["proposed_action"]["title"] == "First proposal"
    assert [a["title"] for a in client.get("/api/v1/actions").json()["actions"]] == ["First proposal"]


@pytest.mark.ac("AC-INV-05")
def test_the_approval_flow_is_unchanged_for_an_agent_proposal(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    client, sink = client_for(port, falkordb, tmp_path, ScriptedModel([text(PLAN), propose()]))
    action_id = client.post("/api/v1/ask", json=ASK).json()["proposed_action"]["id"]
    assert sink.calls == 0
    url = f"/api/v1/actions/{action_id}/approve"
    assert client.post(url, json={"mode": "real"}).status_code == 403
    done = client.post(url, json={"mode": "dry-run"}).json()
    assert (done["status"], done["mode"], done["provenance"]) == ("executed", "dry-run", "agent")
    assert done["result"]["dry_run"] is True
    assert client.post(url, json={"mode": "dry-run"}).status_code == 409
    assert sink.calls == 0


@pytest.mark.ac("AC-INV-05")
def test_a_real_approval_still_needs_the_operator_key(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> None:
    client, sink = client_for(port, falkordb, tmp_path, ScriptedModel([text(PLAN), propose()]))
    action_id = client.post("/api/v1/ask", json=ASK).json()["proposed_action"]["id"]
    url = f"/api/v1/actions/{action_id}/approve"
    assert client.post(url, json={"mode": "real"}, headers={"X-Approver-Key": "wrong"}).status_code == 403
    assert sink.calls == 0
    done = client.post(url, json={"mode": "real"}, headers={"X-Approver-Key": "s3cret"}).json()
    assert (done["status"], done["approver"], sink.calls) == ("executed", "operator", 1)


@pytest.mark.ac("AC-INV-06")
def test_with_actions_off_the_model_is_never_offered_the_tool(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    llm = ScriptedModel([text(PLAN)])
    client, _sink = client_for(port, falkordb, tmp_path, llm, actions=False)
    data = client.post("/api/v1/ask", json=ASK).json()
    assert "proposed_action" not in data
    assert (llm.calls, data["trace"]["llm_calls"]) == (1, 1)


@pytest.mark.ac("AC-INV-05")
def test_the_actions_rate_limiter_caps_agent_proposals(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> None:
    replies = [r for i in range(11) for r in (text(PLAN), propose(f"Follow-up {i}"))]
    client, _sink = client_for(port, falkordb, tmp_path, ScriptedModel(replies))
    made = ["proposed_action" in client.post("/api/v1/ask", json=ASK).json() for _ in range(11)]
    assert made == [True] * 10 + [False]
    assert len(client.get("/api/v1/actions").json()["actions"]) == 10
