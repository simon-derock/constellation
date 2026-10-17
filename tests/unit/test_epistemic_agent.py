import json
from collections.abc import Sequence
from typing import Any

from constellation.agents.epistemic import Question, answer
from constellation.agents.llm import Reply


def call(name: str, **args: object) -> Reply:
    tool_call = {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    return Reply("", (tool_call,), {"role": "assistant", "content": "", "tool_calls": [tool_call]})


def final(payload: dict[str, object]) -> Reply:
    text = json.dumps(payload)
    return Reply(text, (), {"role": "assistant", "content": text})


class ScriptedLLM:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.seen_tools: list[list[str]] = []
        self.seen_messages: list[list[dict[str, Any]]] = []

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        self.seen_tools.append([t["function"]["name"] for t in tools])
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


class StubTools:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, object]]] = []

    def find_events(self, day: int, event_type: str = "", actors: Sequence[str] = ()) -> list[dict[str, object]]:
        self.log.append(("find_events", {"day": day}))
        return [{"event": "EVT-8-incident_opened-1", "type": "incident_opened", "day": day, "actors": ["Jax"]}]

    def event_artifacts(self, event: str) -> list[dict[str, object]]:
        self.log.append(("event_artifacts", {"event": event}))
        return [{"artifact": "ENG-1", "key": "jira"}]

    def absence(self, trigger: str, response_type: str) -> dict[str, object]:
        self.log.append(("absence", {"trigger": trigger}))
        return {"known_expectation": True, "exists": False, "response_event": None, "searched": ["ENG-1"]}

    def could_have_known(self, event: str) -> dict[str, object]:
        raise PermissionError("this tool answers only from an actor's perspective")


SILENCE = Question("q1", "SILENCE", "Was a postmortem written for the Day 8 incident involving Jax?")


def test_one_tool_per_step_until_a_final_answer() -> None:
    llm = ScriptedLLM(
        [
            call("find_events", day=8, event_type="incident_opened", actors=["Jax"]),
            call("absence", trigger="EVT-8-incident_opened-1", response_type="postmortem_created"),
            final({"exists": False, "answer": "no", "reasoning": "nothing found"}),
        ]
    )
    tools = StubTools()
    result = answer(llm, tools, SILENCE)
    assert [name for name, _ in tools.log] == ["find_events", "absence"]
    assert result.answer["exists"] is False
    assert result.stop_reason == "final answer"


def test_silence_offers_only_its_own_tools() -> None:
    llm = ScriptedLLM([final({"exists": False, "answer": "no", "reasoning": "-"})])
    answer(llm, StubTools(), SILENCE)
    assert set(llm.seen_tools[0]) == {"find_events", "absence"}


def test_identical_repeated_calls_are_refused_not_executed() -> None:
    repeat = call("find_events", day=8)
    llm = ScriptedLLM([repeat, repeat, final({"exists": False, "answer": "no", "reasoning": "-"})])
    tools = StubTools()
    result = answer(llm, tools, SILENCE)
    assert [name for name, _ in tools.log] == ["find_events"]
    assert result.refused_repeats == 1


def test_verify_overrides_an_answer_that_contradicts_the_tool_and_says_so() -> None:
    llm = ScriptedLLM(
        [
            call("absence", trigger="EVT-8-incident_opened-1", response_type="postmortem_created"),
            final({"exists": True, "answer": "yes", "reasoning": "probably"}),
        ]
    )
    result = answer(llm, StubTools(), SILENCE)
    assert (result.answer["exists"], result.answer["answer"]) == (False, "no")
    assert "ENG-1" in str(result.answer["reasoning"])
    assert result.strategy_changes == ["verify: exists corrected to the absence tool's decision"]


def test_tool_errors_are_returned_to_the_model_not_raised() -> None:
    llm = ScriptedLLM([call("could_have_known", event="E"), final({"exists": False, "answer": "no", "reasoning": "-"})])
    result = answer(llm, StubTools(), SILENCE)
    assert result.tool_errors == 1


def test_an_exhausted_budget_ends_with_one_tool_free_synthesis() -> None:
    llm = ScriptedLLM([call("find_events", day=d) for d in range(1, 7)] + [final({"exists": False, "answer": "no"})])
    result = answer(llm, StubTools(), SILENCE, max_steps=6)
    assert llm.seen_tools[-1] == []
    assert result.stop_reason == "budget exhausted"


def test_malformed_final_text_gets_one_correction_turn() -> None:
    llm = ScriptedLLM(
        [
            Reply("I think no", (), {"role": "assistant", "content": "I think no"}),
            final({"exists": False, "answer": "no"}),
        ]
    )
    result = answer(llm, StubTools(), SILENCE)
    assert result.answer["exists"] is False
    assert result.protocol_corrections == 1


class CounterfactualTools(StubTools):
    def counterfactual(self, cause: str, effect: str, mechanism: str) -> dict[str, object]:
        self.log.append(("counterfactual", {"cause": cause}))
        return {"linked": True, "outcome_changed": False, "alternative_causes": ["c2"], "actors": ["Jax", "Raj"]}


def test_counterfactual_answers_take_mechanism_outcome_and_people_from_the_tool() -> None:
    q = Question("c1", "COUNTERFACTUAL", "Would the incident still have happened?")
    llm = ScriptedLLM(
        [
            call("counterfactual", cause="c1", effect="e1", mechanism="doc_gap_detected"),
            final({"outcome_changed": True, "causal_mechanism": "involves_gap"}),
        ]
    )
    result = answer(llm, CounterfactualTools(), q)
    assert result.answer["outcome_changed"] is False
    assert result.answer["causal_mechanism"] == "doc_gap_detected"
    assert result.answer["actors"] == ["Jax", "Raj"]


class PerspectiveTools(StubTools):
    def could_have_known(self, event: str) -> dict[str, object]:
        return {"could_actor_have_known": False, "evidence_artifacts": [], "blocked_subsystems": ["git"]}


def test_perspective_answers_report_blocked_subsystems_from_the_tool() -> None:
    q = Question("p1", "PERSPECTIVE", "Could Tom have known?", actor="Tom", day=9, subsystems=("slack",))
    llm = ScriptedLLM([call("could_have_known", event="e"), final({"could_actor_have_known": False})])
    result = answer(llm, PerspectiveTools(), q)
    assert result.answer["blocked_subsystems"] == ["git"]


def test_counterfactual_questions_get_a_larger_step_budget() -> None:
    from constellation.agents.epistemic import STEP_BUDGET

    assert STEP_BUDGET["COUNTERFACTUAL"] > STEP_BUDGET["SILENCE"]


def test_the_loop_warns_two_steps_before_its_budget_ends() -> None:
    llm = ScriptedLLM([call("find_events", day=d) for d in range(1, 7)] + [final({"exists": False, "answer": "no"})])
    answer(llm, StubTools(), SILENCE, max_steps=6)
    warned = [i for i, m in enumerate(llm.seen_messages) if any("Two steps left" in str(x.get("content")) for x in m)]
    assert warned
    assert warned[0] == 4
