import json
from pathlib import Path

import polars as pl
import pytest

from constellation.brain.ownership import Claim, Departure, RegistryEntry, ownership_timeline
from constellation.domain.interval import holder_at
from constellation.ingest.apex import ownership_sources


def _corpus(tmp_path: Path) -> Path:
    rows = [
        ("EVT-2-claim-1", "domain_ownership_claimed", 2, {"domain": "Project Titan", "new_owner": "Sam"}),
        ("EVT-12-dep-1", "employee_departed", 12, {"name": "Jordan", "knowledge_domains": ["auth-service"]}),
        ("EVT-3-other-1", "standup", 3, {"summary": "x"}),
    ]
    path = tmp_path / "c.parquet"
    pl.DataFrame(
        {
            "doc_id": [r[0] for r in rows],
            "doc_type": [r[1] for r in rows],
            "category": ["sim_event"] * 3,
            "day": [r[2] for r in rows],
            "facts": [json.dumps(r[3]) for r in rows],
        }
    ).write_parquet(path)
    return path


def test_sources_come_from_claims_departures_and_the_registry(tmp_path: Path) -> None:
    registry = tmp_path / "r.json"
    registry.write_text(
        json.dumps(
            [{"domain": "Project Titan", "primary_owner": "Sam", "former_owners": ["Bill"], "last_updated_day": 59}]
        )
    )
    entries, claims, departures = ownership_sources(_corpus(tmp_path), registry)
    assert entries == [RegistryEntry("Project Titan", "Sam", ("Bill",), 59)]
    assert claims == [Claim("Project Titan", "Sam", 2, "EVT-2-claim-1")]
    assert departures == [Departure("Jordan", 12, "EVT-12-dep-1")]


def test_real_registry_and_events_produce_one_owner_per_day_for_every_domain() -> None:
    raw = Path("data/raw/apex")
    if not raw.exists():
        pytest.skip("pinned Apex data not fetched")
    entries, claims, departures = ownership_sources(
        raw / "corpus/corpus-00000.parquet", raw / "supplemental/domain_registry.json"
    )
    facts = ownership_timeline(entries, claims, departures)
    assert {f.domain for f in facts} == {e.domain for e in entries}
    for entry in entries:
        for day in range(-700, 61):
            holder_at([(f.owner, f.interval) for f in facts if f.domain == entry.domain], day)
