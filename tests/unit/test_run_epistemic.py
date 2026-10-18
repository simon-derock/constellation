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


def test_resume_skips_completed_questions_and_keeps_their_rows(tmp_path: Path) -> None:
    from constellation.eval.run_epistemic import load_completed, remaining

    ledger = tmp_path / "epistemic-x.jsonl"
    ledger.write_text(
        json.dumps({"question_id": "a", "combined_score": 1.0})
        + "\n"
        + json.dumps({"question_id": "b"})
        + "\n"
        + '{"trunc'
    )
    done = load_completed(ledger)
    assert [r["question_id"] for r in done] == ["a", "b"]
    questions = [{"question_id": q} for q in ("a", "b", "c", "d")]
    assert [q["question_id"] for q in remaining(questions, done)] == ["c", "d"]


def test_resume_of_a_missing_ledger_is_an_error_not_a_fresh_run(tmp_path: Path) -> None:
    from constellation.eval.run_epistemic import load_completed

    with pytest.raises(FileNotFoundError):
        load_completed(tmp_path / "nope.jsonl")


@pytest.mark.parametrize("provider", ["workers", "cohere", "groq", "cerebras", "gemini", "openrouter"])
def test_every_provider_is_a_choice_and_a_missing_key_is_reported_by_name(
    provider: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from constellation.agents.providers import BY_NAME
    from constellation.eval.run_epistemic import main

    for variable in (*BY_NAME[provider].keys, BY_NAME[provider].account):
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(SystemExit) as stop:
        main(["--provider", provider])
    assert stop.value.code == 2
    assert f"{provider} needs" in capsys.readouterr().err


def test_an_unknown_provider_is_refused_before_anything_runs(capsys: pytest.CaptureFixture[str]) -> None:
    from constellation.eval.run_epistemic import main

    with pytest.raises(SystemExit):
        main(["--provider", "openai"])
    assert "invalid choice" in capsys.readouterr().err
