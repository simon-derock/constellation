import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

from constellation.actions.store import ActionRecord
from constellation.agents.acting import PROPOSE_ACTION, ActingToolbox, propose_follow_up
from constellation.agents.epistemic import AgentRun, Question, answer, specs_for
from constellation.agents.llm import LLMError, ModelLock, Reply, WorkersAI
from constellation.agents.toolbox import Toolbox
from constellation.eval import run_epistemic
from constellation.graph.read import ReadPort, ReadResult, canonical_sha256

SILENCE = Question("q1", "SILENCE", "Was a postmortem written for the Day 8 incident involving Jax?")
VERDICT: dict[str, object] = {"exists": False, "answer": "no", "reasoning": "Searched 2 artifacts; no postmortem."}


class FakePort(ReadPort):
    # every catalogue query answers with one row that depends on its parameters, so each call has its own proof
    def __init__(self) -> None:
        pass

    def run(
        self, graph: str, cypher: str, params: Mapping[str, object] | None = None, timeout_ms: int = 2_000
    ) -> ReadResult:
        columns, rows = ("event", "type", "day"), ((json.dumps(params, sort_keys=True), "incident_opened", 8),)
        return ReadResult(columns, rows, canonical_sha256(columns, rows))


class Recorder:
    def __init__(self) -> None:
        self.filed: list[ActionRecord] = []

    def propose(
        self, kind: str, title: str, body: str, evidence: list[dict[str, Any]], provenance: str = "rule"
    ) -> ActionRecord:
        record = ActionRecord(
            id=f"a{len(self.filed)}",
            kind=kind,
            title=title,
            body=body,
            payload_hash="0" * 64,
            status="proposed",
            approver=None,
            mode=None,
            result=None,
            evidence=evidence,
            created="t",
            provenance=provenance,
        )
        self.filed.append(record)
        return record


def call(name: str, **args: object) -> Reply:
    tool_call = {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    return Reply("", (tool_call,), {"role": "assistant", "content": "", "tool_calls": [tool_call]})


def text(body: str) -> Reply:
    return Reply(body, (), {"role": "assistant", "content": body})


class ScriptedLLM:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.seen_tools: list[list[str]] = []
        self.seen_messages: list[list[dict[str, Any]]] = []

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        self.seen_tools.append([t["function"]["name"] for t in tools])
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


def acting(store: Recorder, allow: Callable[[], bool] = lambda: True) -> ActingToolbox:
    tools = ActingToolbox(FakePort(), "g", store=store, allow=allow)
    tools.find_events(8, "incident_opened")
    tools.causal_links("EVT-8-incident_opened-1")
    return tools


def run_of(tools: Toolbox) -> AgentRun:
    return AgentRun(answer=dict(VERDICT), stop_reason="planned", results=[("find_events", {}, [])])


def proposal(**over: object) -> Reply:
    args: dict[str, object] = {
        "title": "Write the postmortem for the Day 8 incident",
        "body": "No postmortem exists for the incident Jax opened on Day 8.",
        "evidence": ["find_events"],
    }
    return call("propose_action", **{**args, **over})


@pytest.mark.ac("AC-T1-04")
def test_a_proposal_is_filed_with_agent_provenance_and_this_runs_proofs() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([proposal(evidence=["find_events", tools.queries[1].sha256])])
    filed = propose_follow_up(llm, tools, SILENCE, run_of(tools))
    assert filed is not None
    assert (filed.provenance, filed.kind, filed.status) == ("agent", "file_issue", "proposed")
    assert filed.title == "Write the postmortem for the Day 8 incident"
    assert [e["sha256"] for e in filed.evidence] == [q.sha256 for q in tools.queries]
    assert [e["name"] for e in filed.evidence] == ["find_events", "causal_links"]
    assert all(q.sha256 in filed.body for q in tools.queries)
    assert "Proposed by the agent" in filed.body
    assert tools.proposed is filed


@pytest.mark.ac("AC-INV-06")
def test_the_model_is_offered_only_propose_action_and_only_after_the_answer() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([proposal()])
    propose_follow_up(llm, tools, SILENCE, run_of(tools))
    assert llm.seen_tools == [["propose_action"]]
    prompt = llm.seen_messages[0]
    assert "Propose only when the answer reveals something that needs follow-up" in prompt[0]["content"]
    assert VERDICT["reasoning"] in prompt[1]["content"]
    assert all(q.sha256 in prompt[1]["content"] for q in tools.queries)
    assert "postmortem" in PROPOSE_ACTION["function"]["description"]


@pytest.mark.ac("AC-INV-05")
@pytest.mark.parametrize(
    "evidence",
    [["f" * 64], ["not_a_query"], [], "find_events", ["find_events", "f" * 64], [7], [["find_events"]]],
    ids=["unknown-hash", "unknown-name", "empty", "bare-string", "one-good-one-forged", "number", "nested"],
)
def test_evidence_that_is_not_this_runs_proof_is_refused_and_nothing_is_written(evidence: object) -> None:
    store = Recorder()
    tools = acting(store)
    with pytest.raises(ValueError, match=r"evidence|not a proof"):
        tools.propose_action("Title", "Body", evidence)  # type: ignore[arg-type]
    assert store.filed == []
    assert tools.proposed is None
    assert tools.calls[-1].tool == "propose_action"
    assert tools.calls[-1].empty is True


@pytest.mark.ac("AC-INV-05")
def test_a_refusal_is_returned_to_the_model_which_gets_one_correction() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([proposal(evidence=["f" * 64]), proposal(evidence=["causal_links"])])
    filed = propose_follow_up(llm, tools, SILENCE, run_of(tools))
    assert filed is not None
    assert [e["name"] for e in filed.evidence] == ["causal_links"]
    observation = llm.seen_messages[1][-1]
    assert observation["role"] == "tool"
    assert "not a proof from this run" in observation["content"]
    assert len(store.filed) == 1


@pytest.mark.ac("AC-INV-05")
def test_two_refusals_end_the_turn_with_no_proposal() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([proposal(evidence=["f" * 64]), proposal(evidence=["e" * 64])])
    assert propose_follow_up(llm, tools, SILENCE, run_of(tools)) is None
    assert llm.replies == []
    assert store.filed == []


@pytest.mark.ac("AC-INV-05")
def test_at_most_one_proposal_per_ask() -> None:
    store = Recorder()
    tools = acting(store)
    assert tools.propose_action("First", "Body", ["find_events"]) == {
        "proposed": True,
        "id": "a0",
        "status": "proposed",
    }
    with pytest.raises(ValueError, match="one proposal per question"):
        tools.propose_action("Second", "Body", ["find_events"])
    assert [r.title for r in store.filed] == ["First"]


@pytest.mark.ac("AC-INV-05")
def test_the_actions_rate_limiter_is_asked_only_for_a_valid_proposal() -> None:
    asked: list[int] = []

    def allow() -> bool:
        asked.append(1)
        return False

    store = Recorder()
    tools = acting(store, allow)
    with pytest.raises(ValueError, match="not a proof from this run"):
        tools.propose_action("Title", "Body", ["f" * 64])
    assert asked == []
    with pytest.raises(PermissionError, match="rate limit"):
        tools.propose_action("Title", "Body", ["find_events"])
    assert (asked, store.filed, tools.proposed) == ([1], [], None)


@pytest.mark.ac("AC-INV-05")
def test_a_limited_proposal_is_not_retried() -> None:
    store = Recorder()
    tools = acting(store, allow=lambda: False)
    llm = ScriptedLLM([proposal()])
    assert propose_follow_up(llm, tools, SILENCE, run_of(tools)) is None
    assert llm.replies == []
    assert store.filed == []


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("", "Body"),
        ("   ", "Body"),
        ("T" * 121, "Body"),
        ("Title", ""),
        ("Title", "B" * 1_501),
        (None, "Body"),
        ("T", 5),
    ],
)
def test_titles_and_bodies_are_bounded_text(title: object, body: object) -> None:
    store = Recorder()
    with pytest.raises(ValueError, match=r"must be|characters"):
        acting(store).propose_action(title, body, ["find_events"])  # type: ignore[arg-type]
    assert store.filed == []


def test_a_title_is_one_line_and_the_body_is_trimmed() -> None:
    store = Recorder()
    acting(store).propose_action("Write the\n  postmortem ", "  Body.\n", ["find_events"])
    assert store.filed[0].title == "Write the postmortem"
    assert store.filed[0].body.startswith("Body.\n\n- Evidence: find_events result hash ")


def test_a_filed_proposal_is_a_step_in_the_trace() -> None:
    tools = acting(Recorder())
    tools.propose_action("Title", "Body", ["find_events"])
    step = tools.calls[-1]
    assert (step.tool, step.result_ids, step.empty) == ("propose_action", ("a0",), False)
    assert step.proofs == (tools.queries[0].sha256,)


def test_a_model_that_proposes_nothing_costs_one_call_and_files_nothing() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([text("NONE")])
    assert propose_follow_up(llm, tools, SILENCE, run_of(tools)) is None
    assert llm.replies == []
    assert store.filed == []


def test_another_tool_name_is_not_a_proposal() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([call("find_events", day=8)])
    assert propose_follow_up(llm, tools, SILENCE, run_of(tools)) is None
    assert len(tools.queries) == 2
    assert store.filed == []


def test_malformed_arguments_are_refused_like_forged_ones() -> None:
    store = Recorder()
    tools = acting(store)
    bad = Reply("", ({"id": "c", "function": {"name": "propose_action", "arguments": "{not json"}},), {})
    extra = proposal(unexpected="x")
    llm = ScriptedLLM([bad, extra])
    assert propose_follow_up(llm, tools, SILENCE, run_of(tools)) is None
    assert store.filed == []


def test_an_answer_with_nothing_to_cite_makes_no_model_call() -> None:
    store = Recorder()
    llm = ScriptedLLM([])
    bare = ActingToolbox(FakePort(), "g", store=store, allow=lambda: True)
    assert propose_follow_up(llm, bare, SILENCE, run_of(bare)) is None
    tools = acting(store)
    assert propose_follow_up(llm, tools, SILENCE, AgentRun(answer={}, stop_reason="")) is None
    assert llm.seen_tools == []


def test_a_model_outage_after_the_answer_costs_only_the_proposal() -> None:
    class Down:
        def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
            raise LLMError("HTTP 429")

    tools = acting(Recorder())
    assert propose_follow_up(Down(), tools, SILENCE, run_of(tools)) is None


@pytest.mark.ac("AC-INV-06")
def test_the_benchmark_toolbox_does_not_expose_the_tool() -> None:
    assert not hasattr(Toolbox, "propose_action")
    assert not hasattr(Toolbox(FakePort(), "g"), "propose_action")
    for kind in ("PERSPECTIVE", "COUNTERFACTUAL", "SILENCE"):
        assert "propose_action" not in [s["function"]["name"] for s in specs_for(kind)]


@pytest.mark.ac("AC-INV-06")
def test_the_react_loop_refuses_propose_action_even_on_the_acting_toolbox() -> None:
    store = Recorder()
    tools = acting(store)
    llm = ScriptedLLM([proposal(), text(json.dumps({"exists": False, "answer": "no", "reasoning": "-"}))])
    run = answer(llm, tools, SILENCE)
    assert run.tool_errors == 1
    assert "propose_action" not in llm.seen_tools[0]
    assert store.filed == []


@pytest.mark.ac("AC-INV-06")
def test_the_benchmark_runner_builds_a_plain_toolbox(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[object] = []

    def solve(llm: object, tools: object, q: Question) -> AgentRun:
        built.append(tools)
        return AgentRun(answer={}, stop_reason="stub")

    def noop(*_args: object, **_kwargs: object) -> Any:
        return {}

    monkeypatch.setattr(run_epistemic, "solve", solve)
    monkeypatch.setattr(run_epistemic, "trajectory", noop)
    monkeypatch.setattr(run_epistemic, "score", noop)
    llm = WorkersAI("acct", "token", ModelLock("m", 0.0, 1))
    raw = {"question_id": "q", "question_type": "SILENCE", "question_text": "t"}
    run_epistemic.run_one(llm, FakePort(), "g", raw, {})
    assert [type(t) for t in built] == [Toolbox]
