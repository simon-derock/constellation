from pathlib import Path

import polars as pl
import pytest

from constellation.ingest.apex import load_apex, parse_artifact_ids, roles_from_config

type Pairs = tuple[tuple[str, str], ...]


@pytest.mark.parametrize(
    ("raw", "pairs"),
    [
        (None, ()),
        ("", ()),
        ('{"jira": "ENG-1", "confluence": ""}', (("jira", "ENG-1"),)),
        ('{"spawned_tickets": ["A-1", "A-2"]}', (("spawned_tickets", "A-1"), ("spawned_tickets", "A-2"))),
    ],
)
def test_artifact_ids_flatten_lists_and_drop_empties(raw: str | None, pairs: tuple[tuple[str, str], ...]) -> None:
    assert parse_artifact_ids(raw) == pairs


def test_roles_cover_org_chart_hires_and_departures(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "org_chart:\n  Engineering_Backend: [Jax]\n  HR_Ops: [Tom]\n"
        "org_lifecycle:\n  scheduled_hires: [{name: Reese, dept: Engineering_Backend}]\n"
        "  scheduled_departures: [{name: Morgan, dept: Engineering_Backend}]\n"
    )
    assert roles_from_config(cfg) == {
        "Jax": "engineering_backend",
        "Tom": "hr_ops",
        "Reese": "engineering_backend",
        "Morgan": "engineering_backend",
    }


def test_loader_splits_events_from_artifacts(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.parquet"
    pl.DataFrame(
        {
            "doc_id": ["EVT-1-standup-1", "CONF-1", "m-1"],
            "doc_type": ["standup", "confluence", "datadog_metric"],
            "category": ["sim_event", "artifact", None],
            "day": [1, 0, 1],
            "timestamp": ["2026-01-02T09:00:00", "2026-01-01T09:00:00", "2026-01-02T00:00:00"],
            "actors": ['["Jax"]', "[]", None],
            "artifact_ids": ['{"slack": "su-1"}', "{}", None],
            "facts": ['{"spawned_doc": false}', "", None],
            "title": ["Standup", "Page", "cpu"],
            "body": ["b", "page body", "1"],
        }
    ).write_parquet(corpus)
    cfg = tmp_path / "c.yaml"
    cfg.write_text("org_chart:\n  Engineering_Backend: [Jax]\norg_lifecycle: {}\n")
    apex = load_apex(corpus, cfg)
    assert [e.event_id for e in apex.events] == ["EVT-1-standup-1"]
    assert apex.events[0].artifact_ids == (("slack", "su-1"),)
    assert [a.doc_id for a in apex.artifacts] == ["CONF-1"]
    assert apex.roles == {"Jax": "engineering_backend"}


def test_events_carry_the_simulators_one_line_summary(tmp_path: Path) -> None:
    corpus = tmp_path / "c.parquet"
    pl.DataFrame(
        {
            "doc_id": ["EVT-1-standup-1"],
            "doc_type": ["standup"],
            "category": ["sim_event"],
            "day": [1],
            "timestamp": ["2026-01-02T09:00:00"],
            "actors": ['["Jax"]'],
            "artifact_ids": ['{"slack": "su-1"}'],
            "facts": ["{}"],
            "title": ["Standup"],
            "body": ["event_type: standup\nsummary: Jax ran standup.\nactors: Jax"],
        }
    ).write_parquet(corpus)
    cfg = tmp_path / "c.yaml"
    cfg.write_text("org_chart:\n  Engineering_Backend: [Jax]\norg_lifecycle: {}\n")
    assert load_apex(corpus, cfg).events[0].summary == "Jax ran standup."
