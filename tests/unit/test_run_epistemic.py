import json
from pathlib import Path

import pytest

from constellation.eval.run_epistemic import question_for_agent

RAW = Path("data/raw/apex/questions/eval_questions.jsonl")


def test_the_agent_sees_only_what_the_official_harness_shows() -> None:
    raw = {
        "question_id": "perspective_X",
        "question_type": "PERSPECTIVE",
        "question_text": "Would Alex have learned about it by Day 28?",
        "actor": "Alex",
        "as_of_day": 28,
        "subsystem_access": ["slack", "jira"],
        "event_id": "EVT-28-secret",
        "ground_truth": {"could_actor_have_known": True},
    }
    q = question_for_agent(raw)
    shown = json.dumps([q.text, q.actor, q.day, q.subsystems])
    assert "EVT-28-secret" not in shown
    assert "could_actor_have_known" not in shown
    assert (q.actor, q.day, q.subsystems) == ("Alex", 28, ("slack", "jira"))


@pytest.mark.parametrize("qtype", ["COUNTERFACTUAL", "SILENCE"])
def test_non_perspective_questions_carry_no_actor_frame(qtype: str) -> None:
    q = question_for_agent({"question_id": "q", "question_type": qtype, "question_text": "t", "actor": "Alex"})
    assert (q.actor, q.day, q.subsystems) == ("", 0, ())


def test_no_real_question_leaks_its_event_ids_or_answers_into_agent_input() -> None:
    if not RAW.exists():
        pytest.skip("pinned Apex data not fetched")
    for line in RAW.read_text().splitlines():
        raw = json.loads(line)
        q = question_for_agent(raw)
        shown = json.dumps([q.text, q.actor, q.day, q.subsystems])
        hidden = {raw.get("event_id"), raw.get("trigger_event_id"), raw["ground_truth"].get("cause_event_id")}
        assert not {h for h in hidden if h and h in shown}, raw["question_id"]
