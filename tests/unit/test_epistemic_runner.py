from typing import Any

from constellation.agents.epistemic import AgentRun
from constellation.agents.toolbox import ToolRecord
from constellation.eval.epistemic import score, summarize, trajectory


def rec(tool: str, ids: tuple[str, ...] = (), types: tuple[str, ...] = (), empty: bool = False) -> ToolRecord:
    return ToolRecord(tool, {"x": 1}, ids, types, ("0" * 64,), 1.0, empty)


SILENCE_Q = {
    "question_id": "s1",
    "question_type": "SILENCE",
    "expected_search_space": ["ENG-1", "inc-1"],
    "ground_truth": {"answer": False},
}


def test_a_complete_silence_search_reaches_the_track_maximum() -> None:
    records = [
        rec("find_events"),
        rec("event_artifacts", ("ENG-1", "inc-1"), ("jira", "slack")),
        rec("absence", ("ENG-1", "inc-1"), ("artifact", "artifact")),
        rec("event_artifacts", ("inc-1",), ("slack",)),
    ]
    reasoning = "no postmortem was found, so it does not exist"
    run = AgentRun(answer={"exists": False, "answer": "no", "reasoning": reasoning}, stop_reason="final answer")
    result = score(SILENCE_Q, trajectory(SILENCE_Q, records, run, cone=None), cone=None)
    assert result["answer_correct"] is True
    # upstream caps SILENCE trajectory at 0.9 (0.5 coverage, 0.3 negative, 0.1 horizon; no penalty at 4+ calls)
    assert result["trajectory_score"] == 0.9


def test_perspective_violations_are_counted_against_the_cone() -> None:
    q = {
        "question_id": "p1",
        "question_type": "PERSPECTIVE",
        "subsystem_access": ["slack"],
        "ground_truth": {"could_actor_have_known": True, "evidence_artifacts": ["s-1"]},
    }
    records = [rec("event_artifacts", ("s-1", "ENG-9"), ("slack", "jira"))]
    run = AgentRun(answer={"could_actor_have_known": True, "evidence_artifacts": ["s-1"]}, stop_reason="final answer")
    traj = trajectory(q, records, run, cone=frozenset({"s-1"}))
    assert traj.tool_calls[0].actor_gate_violation is True
    assert traj.tool_calls[0].subsystem_violation is True


def test_dead_ends_count_as_recovered_when_a_later_call_finds_something() -> None:
    q = {
        "question_id": "s2",
        "question_type": "SILENCE",
        "expected_search_space": [],
        "ground_truth": {"answer": False},
    }
    run = AgentRun(answer={}, stop_reason="final answer")
    traj = trajectory(q, [rec("find_events", empty=True), rec("find_events")], run, cone=None)
    assert (traj.dead_ends_hit, traj.dead_ends_recovered) == (1, 1)


def row(qtype: str, combined: float, violations: int) -> dict[str, Any]:
    return {
        "question_type": qtype,
        "combined_score": combined,
        "answer_correct": True,
        "tool_calls": 4,
        "actor_gate_violations": violations,
    }


def test_the_summary_applies_the_violation_adjustment() -> None:
    summary = summarize([row("PERSPECTIVE", 1.0, 1), row("SILENCE", 0.5, 0)])
    assert summary["combined_score"] == 0.75
    assert summary["violation_rate"] == 0.25
    assert summary["violation_adjusted_combined_score"] == round(0.75 * 0.75**2, 4)
