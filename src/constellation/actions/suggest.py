import hashlib
import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# the simulation's records begin on day 0; before that, an empty span is missing history, not a gap in ownership
_RECORDS_BEGIN = 0


@dataclass(frozen=True, slots=True)
class Gap:
    domain: str
    start: int
    end: int
    previous_owner: str
    next_owner: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    kind: str
    title: str
    body: str
    payload_hash: str


def ownership_gaps(domains: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[Gap]:
    # a gap is a recorded stretch with no owner between one owner's departure and the next owner's recorded claim
    gaps: list[Gap] = []
    for domain, spans in sorted(domains.items()):
        ordered = sorted(spans, key=lambda s: s["from"])
        for before, after in itertools.pairwise(ordered):
            if before["to"] is None or not after["start_known"]:
                continue
            start, end = max(before["to"], _RECORDS_BEGIN), after["from"]
            if end > start:
                gaps.append(Gap(domain, start, end, before["owner"], after["owner"], str(after["evidence"])))
    return gaps


def _suggestion(gap: Gap, proof_hash: str) -> Suggestion:
    title = f"Ownership gap: {gap.domain} had no owner from day {gap.start} to day {gap.end}"
    body = (
        f"{gap.domain} had no recorded owner from day {gap.start} until day {gap.end}.\n\n"
        f"- Previous owner: {gap.previous_owner}\n"
        f"- Next owner: {gap.next_owner} (claim recorded in {gap.evidence})\n"
        f"- Evidence: ownership timeline query, result hash {proof_hash}; replay it to verify.\n\n"
        "Suggested follow-up: confirm the domain's coverage during the gap and whether anything was left undocumented."
    )
    payload = json.dumps({"kind": "file_issue", "title": title, "body": body}, sort_keys=True, separators=(",", ":"))
    return Suggestion("file_issue", title, body, hashlib.sha256(payload.encode()).hexdigest())


def suggestions_from_rows(domains: Mapping[str, Sequence[Mapping[str, Any]]], proof_hash: str) -> list[Suggestion]:
    return [_suggestion(gap, proof_hash) for gap in ownership_gaps(domains)]
