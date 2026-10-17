import json
from collections.abc import Sequence
from typing import Any

from constellation.agents.epistemic import Question
from constellation.agents.llm import Reply
from constellation.agents.planner import Plan, extract_plan, run_planned

TYPES = ["absence_x", "design_discussion", "incident_opened", "knowledge_gap_detected", "sf_deals_risk_flagged"]


def text(payload: object) -> Reply:
    body = json.dumps(payload)
    return Reply(body, (), {"role": "assistant", "content": body})


class LLM:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.calls = 0

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        self.calls += 1
        return self.replies.pop(0)


class Fake:
    def __init__(self, events: list[dict[str, Any]], links: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.events = events
        self.links = links or {}
        self.log: list[str] = []

    def event_types(self) -> list[str]:
        return TYPES

    def find_events(self, day: int, event_type: str = "", actors: Sequence[str] = ()) -> list[dict[str, Any]]:
        self.log.append(f"find_events:{event_type}")
        hits = [e for e in self.events if e["day"] == day and event_type in ("", e["type"])]
        return hits or [{"no_match": True, "event_types_on_day": []}]

    def event_artifacts(self, event: str) -> list[dict[str, Any]]:
        self.log.append(f"event_artifacts:{event}")
        return [{"artifact": f"A-{event}", "key": "jira"}]

    def causal_links(self, event: str) -> list[dict[str, Any]]:
        self.log.append(f"causal_links:{event}")
        return self.links.get(event, [])

    def counterfactual(self, cause: str, effect: str, mechanism: str) -> dict[str, Any]:
        self.log.append(f"counterfactual:{cause}->{effect}:{mechanism}")
        return {"linked": True, "outcome_changed": True, "alternative_causes": [], "actors": ["Raj"]}

    def could_have_known(self, event: str) -> dict[str, Any]:
        self.log.append(f"could_have_known:{event}")
        return {"could_actor_have_known": True, "evidence_artifacts": ["s-1"], "blocked_subsystems": []}

    def absence(self, trigger: str, response_type: str) -> dict[str, Any]:
        self.log.append(f"absence:{trigger}:{response_type}")
        return {"known_expectation": True, "exists": False, "response_event": None, "searched": ["A-1", "A-2"]}


def ev(eid: str, day: int, kind: str) -> dict[str, Any]:
    return {"event": eid, "type": kind, "day": day, "actors": ["Jax"], "via_artifacts": [], "summary": eid}


def test_a_plan_is_constrained_to_the_graphs_vocabulary() -> None:
    q = Question("q", "SILENCE", "Was a risk flag raised after the Day 8 incident?")
    good = {"day": 8, "event_type": "incident_opened", "people": ["Jax"], "target_type": "sf_deals_risk_flagged"}
    assert extract_plan(LLM([text(good)]), q, TYPES) == Plan(8, "incident_opened", ("Jax",), "sf_deals_risk_flagged")
    bad = {**good, "event_type": "made_up_type"}
    assert extract_plan(LLM([text(bad), text(bad)]), q, TYPES) is None


def test_perspective_with_one_candidate_needs_no_second_model_call() -> None:
    q = Question(
        "p", "PERSPECTIVE", "Would Alex have learned of it by Day 28?", actor="Alex", day=28, subsystems=("slack",)
    )
    llm = LLM([text({"day": 28, "event_type": "incident_opened", "people": [], "target_type": ""})])
    tools = Fake([ev("E28", 28, "incident_opened")])
    run = run_planned(llm, tools, q)
    assert run is not None
    assert llm.calls == 1
    assert tools.log[-1] == "could_have_known:E28"
    assert run.answer["could_actor_have_known"] is True


def test_silence_searches_trigger_artifacts_and_the_response_before_concluding() -> None:
    q = Question("s", "SILENCE", "Was a risk flag raised after the Day 8 incident?")
    plan = {"day": 8, "event_type": "incident_opened", "people": ["Jax"], "target_type": "sf_deals_risk_flagged"}
    tools = Fake([ev("E8", 8, "incident_opened")])
    run = run_planned(LLM([text(plan)]), tools, q)
    assert run is not None
    assert tools.log == [
        "find_events:incident_opened",
        "event_artifacts:E8",
        "find_events:sf_deals_risk_flagged",
        "absence:E8:sf_deals_risk_flagged",
    ]
    assert run.answer["exists"] is False


def test_counterfactual_keeps_only_candidates_whose_links_reach_the_target_type() -> None:
    q = Question("c", "COUNTERFACTUAL", "Without the Day 4 gap, would the incident still have happened?")
    plan = {"day": 4, "event_type": "knowledge_gap_detected", "people": ["Jax"], "target_type": "incident_opened"}
    link = {"cause": "G2", "effect": "I8", "effect_type": "incident_opened", "mechanism": "doc_gap_detected"}
    tools = Fake([ev("G1", 4, "knowledge_gap_detected"), ev("G2", 4, "knowledge_gap_detected")], {"G2": [link]})
    run = run_planned(LLM([text(plan)]), tools, q)
    assert run is not None
    assert tools.log[-3:] == ["event_artifacts:G2", "event_artifacts:I8", "counterfactual:G2->I8:doc_gap_detected"]
    assert run.answer["causal_mechanism"] == "doc_gap_detected"


def test_ambiguity_is_settled_by_one_choice_call_restricted_to_the_candidates() -> None:
    q = Question("p", "PERSPECTIVE", "Would Alex have learned of it by Day 28?", actor="Alex", day=28, subsystems=())
    plan = {"day": 28, "event_type": "incident_opened", "people": [], "target_type": ""}
    tools = Fake([ev("E1", 28, "incident_opened"), ev("E2", 28, "incident_opened")])
    llm = LLM([text(plan), text({"event": "not-a-candidate"}), text({"event": "E2"})])
    run = run_planned(llm, tools, q)
    assert run is not None
    assert tools.log[-1] == "could_have_known:E2"


def test_an_unresolvable_plan_hands_over_to_the_free_loop() -> None:
    q = Question("p", "PERSPECTIVE", "Would Alex have learned of it by Day 28?", actor="Alex", day=28, subsystems=())
    llm = LLM([text({"day": 28, "event_type": "incident_opened", "people": [], "target_type": ""})])
    assert run_planned(llm, Fake([]), q) is None


def test_counterfactual_examines_every_candidate_not_just_the_top_few() -> None:
    q = Question("c", "COUNTERFACTUAL", "Without the design-doc gap, would the incident still have happened?")
    plan = {"day": 4, "event_type": "knowledge_gap_detected", "people": ["Jax"], "target_type": "incident_opened"}
    events = [ev(f"G{i}", 4, "knowledge_gap_detected") for i in range(12)]
    link = {"cause": "G11", "effect": "I8", "effect_type": "incident_opened", "mechanism": "doc_gap_detected"}
    tools = Fake(events, {"G11": [link]})
    run = run_planned(LLM([text(plan)]), tools, q)
    assert run is not None
    assert tools.log[-1] == "counterfactual:G11->I8:doc_gap_detected"


def test_the_chooser_sees_each_links_cause_summary_and_mechanism() -> None:
    seen: list[str] = []

    class Spy(LLM):
        def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
            seen.append(str(messages[-1]["content"]))
            return super().chat(messages, tools)

    q = Question("c", "COUNTERFACTUAL", "Without the design-doc gap, would the incident still have happened?")
    plan = {"day": 4, "event_type": "knowledge_gap_detected", "people": [], "target_type": "incident_opened"}
    links = {
        "G1": [
            {
                "cause": "G1",
                "effect": "I8",
                "effect_type": "incident_opened",
                "mechanism": "involves_gap",
                "cause_summary": "Genesis gap seeded",
            }
        ],
        "G2": [
            {
                "cause": "G2",
                "effect": "I8",
                "effect_type": "incident_opened",
                "mechanism": "doc_gap_detected",
                "cause_summary": "Knowledge gap detected in CONF-ENG-041",
            }
        ],
    }
    tools = Fake([ev("G1", 4, "knowledge_gap_detected"), ev("G2", 4, "knowledge_gap_detected")], links)
    run = run_planned(Spy([text(plan), text({"option": "1"})]), tools, q)
    assert run is not None
    assert "Knowledge gap detected in CONF-ENG-041" in seen[-1]
    assert "doc_gap_detected" in seen[-1]
    assert tools.log[-1] == "counterfactual:G2->I8:doc_gap_detected"
