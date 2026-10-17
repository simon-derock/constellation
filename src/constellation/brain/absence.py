from collections.abc import Sequence
from dataclasses import dataclass

from constellation._vendor.orgforge_causal import _SILENCE_PAIRS, AbsenceCatalogBuilder, _safe_artifact_values
from constellation.ingest.apex import RawEvent

_LINK_FIELD = {(trigger, response): field for trigger, response, field in _SILENCE_PAIRS}


@dataclass(frozen=True, slots=True)
class AbsenceAnswer:
    responded: bool
    # what had to be searched before "no" is a conclusion and not a guess
    search_space: tuple[str, ...]
    response_event: str | None


def link_field_for(trigger_type: str, response_type: str) -> str:
    return _LINK_FIELD[(trigger_type, response_type)]


def check_absence(events: Sequence[RawEvent], trigger: RawEvent, response_type: str) -> AbsenceAnswer:
    # the decision loop of OrgForge AbsenceCatalogBuilder.build (eval_harness.py @ 1da5e4b), per trigger,
    # without its 8-per-type sampling cap; match keys and search spaces come from the vendored methods
    rules = AbsenceCatalogBuilder(list(events))
    link_field = link_field_for(trigger.type, response_type)
    trigger_artifacts = set(_safe_artifact_values(trigger.artifact_ids))
    link_key = rules._match_key(trigger, link_field)
    if trigger.type == "knowledge_gap_detected" and trigger.facts.get("detection_method") == "author_self_audit":
        audited = trigger.artifact_ids.get("confluence")
        if audited:
            trigger_artifacts.discard(str(audited))
    search_space: list[str] = rules._expected_search_space(trigger, response_type)
    for event in events:
        if event.type != response_type or event.day < trigger.day:
            continue
        if _keyed_match(link_key, rules._match_key(event, link_field), event):
            return _responded(search_space, event)
        if trigger_artifacts & set(_safe_artifact_values(event.artifact_ids)):
            return _responded(search_space, event)
    return AbsenceAnswer(responded=False, search_space=tuple(search_space), response_event=None)


def _keyed_match(link_key: str | None, event_key: str | None, event: RawEvent) -> bool:
    # a response matches on the shared key itself, or by carrying the trigger's key anywhere in its record
    if not link_key or event_key is None:
        return False
    return event_key == link_key or link_key in str(event.artifact_ids) or link_key in str(event.facts)


def _responded(search_space: list[str], event: RawEvent) -> AbsenceAnswer:
    # a confirmed response widens the space by the response's own artifacts, as the catalogue records it
    enriched = list(dict.fromkeys(search_space + sorted(_safe_artifact_values(event.artifact_ids))))
    return AbsenceAnswer(responded=True, search_space=tuple(enriched), response_event=event.mongo_id)
