import json
from typing import Any

import pytest

from constellation.agents.epistemic import (
    MECH_GLOSS,
    MECHANISMS,
    TOOLSETS,
    Question,
    compact,
    specs_for,
    system_prompt,
)

# upper bounds in characters (about four per token); a prompt that grows past them is a regression
PROMPT_BUDGET = {"PERSPECTIVE": 800, "SILENCE": 800, "COUNTERFACTUAL": 2_000}
VOCAB = ["incident_opened", "knowledge_gap_detected"]


def question(qtype: str) -> Question:
    return Question("q", qtype, "text", actor="Alex", day=28, subsystems=("slack",))


@pytest.mark.parametrize("qtype", sorted(PROMPT_BUDGET))
def test_every_track_prompt_is_a_react_protocol_within_its_budget(qtype: str) -> None:
    prompt = system_prompt(question(qtype))
    assert all(word in prompt for word in ("Thought", "Action", "Observation"))
    assert len(prompt) <= PROMPT_BUDGET[qtype], len(prompt)


def test_the_glossary_covers_exactly_the_mechanisms_the_graph_contains() -> None:
    graph_mechanisms = {
        "async_gap_detected", "departure_reassignment", "doc_gap_detected", "escalation_from_zendesk",
        "hire_fills_knowledge_gap", "incident_coordination", "involves_gap", "jira_from_vendor_email",
        "postmortem_from_incident", "pr_gap_detected", "recurrence_of", "review_triggers_revision", "spawned_doc",
    }  # fmt: skip
    assert set(MECH_GLOSS) == graph_mechanisms
    assert set(MECH_GLOSS) <= set(MECHANISMS)
    assert all(len(gloss) <= 90 for gloss in MECH_GLOSS.values())


def test_the_counterfactual_prompt_defines_each_mechanism_once() -> None:
    prompt = system_prompt(question("COUNTERFACTUAL"))
    assert all(f"{name}=" in prompt for name in MECH_GLOSS)


def test_counterfactual_needs_only_two_tools_and_the_others_need_two_as_well() -> None:
    assert TOOLSETS["COUNTERFACTUAL"] == ("candidate_links", "counterfactual")
    assert TOOLSETS["SILENCE"] == ("find_events", "absence")
    assert TOOLSETS["PERSPECTIVE"] == ("find_events", "could_have_known")


def test_schemas_constrain_event_types_and_mechanisms_to_real_values() -> None:
    specs = {
        s["function"]["name"]: s["function"]["parameters"]["properties"] for s in specs_for("COUNTERFACTUAL", VOCAB)
    }
    links = specs["candidate_links"]
    assert links["event_type"]["enum"] == ["", *VOCAB]
    assert links["target_type"]["enum"] == ["", *VOCAB]
    assert set(links["mechanism"]["enum"]) == set(MECH_GLOSS)
    assert set(specs["counterfactual"]["mechanism"]["enum"]) == set(MECH_GLOSS)


def test_tool_specs_stay_small() -> None:
    sizes = {q: len(json.dumps(specs_for(q, VOCAB), separators=(",", ":"))) for q in TOOLSETS}
    assert sizes["COUNTERFACTUAL"] <= 1_900
    assert sizes["SILENCE"] <= 1_300
    assert sizes["PERSPECTIVE"] <= 900


def test_observations_are_compact_json_and_capped() -> None:
    assert compact({"a": [1, 2], "b": None}, 100) == '{"a":[1,2],"b":null}'
    big: dict[str, Any] = {"rows": ["x" * 50] * 100}
    assert len(compact(big, 300)) == 300
