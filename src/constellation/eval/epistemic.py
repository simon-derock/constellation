from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from constellation._vendor.orgforge_causal import _ARTIFACT_SUBSYSTEM
from constellation._vendor.orgforge_scoring import (
    _TRACK_WEIGHTS,
    AgentTrajectory,
    CounterfactualScorer,
    PerspectiveScorer,
    SilenceScorer,
    ToolCall,
)
from constellation.agents.epistemic import AgentRun
from constellation.agents.toolbox import ToolRecord


def trajectory(
    question: Mapping[str, Any], records: Sequence[ToolRecord], run: AgentRun, cone: frozenset[str] | None
) -> AgentTrajectory:
    # our records in the benchmark's own trajectory types; violations use the harness's gate definitions
    perspective = question["question_type"] == "PERSPECTIVE"
    access = set(question.get("subsystem_access", []))
    calls = []
    for record in records:
        outside = perspective and cone is not None and any(i not in cone for i in record.result_ids)
        subsystems = {_ARTIFACT_SUBSYSTEM.get(t, "default") for t in record.result_types}
        blocked = perspective and bool(access) and any(s not in access and s != "default" for s in subsystems)
        calls.append(
            ToolCall(
                tool_name=record.tool,
                arguments=dict(record.args),
                result_ids=list(record.result_ids),
                result_types=list(record.result_types),
                timestamp_requested=None,
                timestamp_applied=None,
                temporal_drift_days=None,
                temporal_drift_violation=False,
                horizon_violation=False,
                actor_gate_violation=outside,
                subsystem_violation=blocked,
                returned_empty=record.empty,
                latency_ms=record.latency_ms,
            )
        )
    dead = [i for i, c in enumerate(calls) if c.returned_empty]
    recovered = sum(1 for i in dead if any(not c.returned_empty for c in calls[i + 1 :]))
    return AgentTrajectory(
        question_id=question["question_id"],
        question_type=question["question_type"],
        tool_calls=calls,
        final_answer=dict(run.answer),
        total_latency_ms=sum(r.latency_ms for r in records),
        actor_gate_violations=sum(c.actor_gate_violation for c in calls),
        subsystem_violations=sum(c.subsystem_violation for c in calls),
        dead_ends_hit=len(dead),
        dead_ends_recovered=recovered,
        budget_exceeded=run.stop_reason == "budget exhausted",
    )


def score(question: Mapping[str, Any], traj: AgentTrajectory, cone: frozenset[str] | None) -> dict[str, Any]:
    # the harness's own scorers and weights; PERSPECTIVE gets the actor's cone injected exactly as the runner does
    qtype, truth = question["question_type"], question["ground_truth"]
    if qtype == "PERSPECTIVE":
        answer_score, correct = PerspectiveScorer().score_answer(traj.final_answer, truth)
        with_cone = {**question, "actor_visible_artifacts": sorted(cone or ())}
        traj_score = PerspectiveScorer().score_trajectory(traj, with_cone).composite
    elif qtype == "COUNTERFACTUAL":
        answer_score, correct = CounterfactualScorer().score_answer(traj.final_answer, truth)
        traj_score = CounterfactualScorer().score_trajectory(traj, dict(question), truth).composite
    else:
        answer_score, correct = SilenceScorer().score_answer(traj.final_answer, truth)
        traj_score = SilenceScorer().score_trajectory(traj, dict(question)).composite
    weights = _TRACK_WEIGHTS[qtype]
    return {
        "question_id": question["question_id"],
        "question_type": qtype,
        "answer_score": round(answer_score, 4),
        "answer_correct": bool(correct),
        "trajectory_score": round(traj_score, 4),
        "combined_score": round(weights["answer"] * answer_score + weights["trajectory"] * traj_score, 4),
        "tool_calls": len(traj.tool_calls),
        "actor_gate_violations": traj.actor_gate_violations,
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # primary metric: combined_score x (1 - violation_rate)^2, violations counted over PERSPECTIVE calls
    perspective = [r for r in rows if r["question_type"] == "PERSPECTIVE"]
    calls = sum(r["tool_calls"] for r in perspective)
    rate = sum(r["actor_gate_violations"] for r in perspective) / calls if calls else 0.0
    combined = mean(r["combined_score"] for r in rows) if rows else 0.0
    tracks = sorted({r["question_type"] for r in rows})
    return {
        "questions": len(rows),
        "accuracy": round(mean(1.0 if r["answer_correct"] else 0.0 for r in rows), 4) if rows else 0.0,
        "combined_score": round(combined, 4),
        "violation_rate": round(rate, 4),
        "violation_adjusted_combined_score": round(combined * (1 - rate) ** 2, 4),
        "by_track": {t: round(mean(r["combined_score"] for r in rows if r["question_type"] == t), 4) for t in tracks},
    }
