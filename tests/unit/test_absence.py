import random
from pathlib import Path

import pytest

from constellation._vendor.orgforge_causal import AbsenceCatalogBuilder
from constellation.brain.absence import check_absence, link_field_for
from constellation.ingest.apex import RawEvent, raw_events


def ev(eid: str, day: int, type_: str, ids: dict[str, object], facts: dict[str, object] | None = None) -> RawEvent:
    return RawEvent(type_, day, "", f"2026-01-{day + 1:02d}T09:00:00", ["Jax"], ids, facts or {}, "", [], eid)


class _EmptyCollections:
    # build() reads CRM collections only to enrich records, never to decide them
    def __getitem__(self, _name: str) -> "_EmptyCollections":
        return self

    def find(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []


class _Memory:
    _db = _EmptyCollections()


INCIDENT = ev("EVT-3-inc", 3, "incident_opened", {"jira": "ENG-7", "slack": "inc-7"})


def test_a_missing_postmortem_is_an_absence_with_its_search_space() -> None:
    answer = check_absence([INCIDENT], INCIDENT, "postmortem_created")
    assert not answer.responded
    assert set(answer.search_space) >= {"ENG-7", "inc-7"}


def test_a_postmortem_citing_the_ticket_is_a_response() -> None:
    pm = ev("EVT-5-pm", 5, "postmortem_created", {"confluence": "PM-7", "jira": "ENG-7"})
    answer = check_absence([INCIDENT, pm], INCIDENT, "postmortem_created")
    assert answer.responded
    assert answer.response_event == "EVT-5-pm"


def test_a_response_before_the_trigger_does_not_count() -> None:
    early = ev("EVT-1-pm", 1, "postmortem_created", {"confluence": "PM-1", "jira": "ENG-7"})
    assert not check_absence([early, INCIDENT], INCIDENT, "postmortem_created").responded


def test_link_fields_come_from_the_silence_pairs() -> None:
    assert link_field_for("incident_opened", "postmortem_created") == "jira"
    with pytest.raises(KeyError):
        link_field_for("standup", "postmortem_created")


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_matches_the_vendored_catalogue_on_real_data(seed: int) -> None:
    corpus = Path("data/raw/apex/corpus/corpus-00000.parquet")
    if not corpus.exists():
        pytest.skip("pinned Apex data not fetched")
    events = raw_events(corpus)
    by_id = {e.mongo_id: e for e in events}
    random.seed(seed)
    absent, confirmed = AbsenceCatalogBuilder(events, mem=_Memory()).build()
    assert absent
    assert confirmed
    for record, responded in [(r, False) for r in absent] + [(r, True) for r in confirmed]:
        answer = check_absence(events, by_id[record.trigger_event_id], record.expected_response_type)
        assert answer.responded is responded, record.trigger_event_id
        assert list(answer.search_space) == record.expected_search_space, record.trigger_event_id
