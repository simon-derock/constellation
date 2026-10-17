import json
from pathlib import Path

import polars as pl

from constellation.brain.causality import CausalEdge, counterfactual, index_causal_links
from constellation.ingest.apex import RawEvent, raw_events


def raw(
    eid: str, day: int, type_: str, ids: dict[str, object], ts: str = "", facts: dict[str, object] | None = None
) -> RawEvent:
    return RawEvent(
        type=type_,
        day=day,
        date="",
        timestamp=ts or f"2026-01-{day + 1:02d}T09:00:00",
        actors=["Jax"],
        artifact_ids=ids,
        facts=facts or {},
        summary="",
        tags=[],
        mongo_id=eid,
    )


INCIDENT = raw("EVT-3-inc-1", 3, "incident_opened", {"jira": "ENG-1"})
POSTMORTEM = raw("EVT-5-pm-1", 5, "postmortem_created", {"confluence": "PM-1", "jira": "ENG-1"})


def test_the_vendored_rules_link_an_incident_to_its_postmortem() -> None:
    edges = index_causal_links([INCIDENT, POSTMORTEM])
    assert CausalEdge("postmortem_from_incident", "EVT-3-inc-1", "EVT-5-pm-1", 3) in edges


def test_indexing_is_deterministic_and_order_free_in_its_output() -> None:
    assert index_causal_links([INCIDENT, POSTMORTEM]) == index_causal_links([INCIDENT, POSTMORTEM])


def test_a_lone_cause_changes_the_outcome() -> None:
    edges = [CausalEdge("pr_gap_detected", "c1", "e1", 4)]
    answer = counterfactual(edges, "pr_gap_detected", "c1", "e1")
    assert (answer.linked, answer.changed, answer.alternatives) == (True, True, ())


def test_a_same_mechanism_alternative_means_the_effect_still_happens() -> None:
    edges = [CausalEdge("doc_gap_detected", "c1", "e1", 4), CausalEdge("doc_gap_detected", "c2", "e1", 3)]
    answer = counterfactual(edges, "doc_gap_detected", "c1", "e1")
    assert (answer.changed, answer.alternatives) == (False, ("c2",))


def test_a_different_mechanism_is_not_redundancy() -> None:
    edges = [CausalEdge("doc_gap_detected", "c1", "e1", 4), CausalEdge("involves_gap", "c2", "e1", 3)]
    assert counterfactual(edges, "doc_gap_detected", "c1", "e1").changed


def test_an_unlinked_pair_is_reported_as_unlinked() -> None:
    assert not counterfactual([], "doc_gap_detected", "c1", "e1").linked


def test_raw_events_run_in_chronological_order(tmp_path: Path) -> None:
    rows = [
        ("EVT-2-b-1", 2, "2026-01-03T10:00:00"),
        ("EVT-1-a-1", 1, "2026-01-02T09:00:00"),
        ("EVT-2-a-2", 2, "2026-01-03T08:00:00"),
    ]
    path = tmp_path / "c.parquet"
    pl.DataFrame(
        {
            "doc_id": [r[0] for r in rows],
            "doc_type": ["standup"] * 3,
            "category": ["sim_event"] * 3,
            "day": [r[1] for r in rows],
            "date": [""] * 3,
            "timestamp": [r[2] for r in rows],
            "actors": ['["Jax"]'] * 3,
            "artifact_ids": [json.dumps({"slack": "s"})] * 3,
            "facts": ["{}"] * 3,
            "tags": ['["slack"]'] * 3,
        }
    ).write_parquet(path)
    assert [e.mongo_id for e in raw_events(path)] == ["EVT-1-a-1", "EVT-2-a-2", "EVT-2-b-1"]
