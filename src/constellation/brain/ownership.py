from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from constellation.domain.interval import Interval, holder_at

# the earliest simulation day any Apex record can carry; ownership before evidence starts here
GENESIS = -1_000


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    domain: str
    primary_owner: str
    # succession order as the registry records it
    former_owners: tuple[str, ...]
    snapshot_day: int


@dataclass(frozen=True, slots=True)
class Claim:
    domain: str
    owner: str
    day: int
    event_id: str


@dataclass(frozen=True, slots=True)
class Departure:
    name: str
    day: int
    event_id: str


@dataclass(frozen=True, slots=True)
class OwnershipFact:
    domain: str
    owner: str
    interval: Interval
    # claim | former_owner | registry_snapshot: how much the evidence actually says
    origin: str
    evidence: str
    start_known: bool


@dataclass(frozen=True, slots=True)
class OwnerAnswer:
    owner: str | None
    origin: str
    evidence: str
    start_known: bool


@dataclass(frozen=True, slots=True)
class _Opening:
    owner: str
    start: int
    hard_end: int | None
    origin: str
    evidence: str
    start_known: bool


def _openings(entry: RegistryEntry, claims: Sequence[Claim], left: dict[str, Departure]) -> list[_Opening]:
    out: list[_Opening] = []
    start = GENESIS
    for name in entry.former_owners:
        dep = left.get(name)
        out.append(_Opening(name, start, dep.day if dep else None, "former_owner", dep.event_id if dep else "", False))
        start = dep.day if dep else start
    out.extend(_Opening(c.owner, c.day, None, "claim", c.event_id, True) for c in sorted(claims, key=lambda c: c.day))
    latest = max(claims, key=lambda c: c.day, default=None)
    # the registry is a snapshot: it proves who owned the domain on that day, not since when
    if latest is None or latest.owner != entry.primary_owner:
        out.append(_Opening(entry.primary_owner, entry.snapshot_day, None, "registry_snapshot", "registry", False))
    return sorted(out, key=lambda o: o.start)


def ownership_timeline(
    registry: Iterable[RegistryEntry], claims: Iterable[Claim], departures: Iterable[Departure]
) -> list[OwnershipFact]:
    left = {d.name: d for d in departures}
    by_domain: dict[str, list[Claim]] = {}
    for claim in claims:
        by_domain.setdefault(claim.domain, []).append(claim)
    facts: list[OwnershipFact] = []
    for entry in registry:
        openings = _openings(entry, by_domain.get(entry.domain, []), left)
        for i, op in enumerate(openings):
            # an interval ends at the owner's departure or the next opening, whichever comes first
            ends = [e for e in (op.hard_end, openings[i + 1].start if i + 1 < len(openings) else None) if e is not None]
            end = min(ends) if ends else None
            if end is not None and end <= op.start:
                continue
            facts.append(
                OwnershipFact(entry.domain, op.owner, Interval(op.start, end), op.origin, op.evidence, op.start_known)
            )
    return facts


def owner_as_of(facts: Sequence[OwnershipFact], domain: str, day: int) -> OwnerAnswer:
    mine = [f for f in facts if f.domain == domain]
    if not mine:
        raise KeyError(domain)
    holder = holder_at([(f, f.interval) for f in mine], day)
    if holder is None:
        return OwnerAnswer(None, "orphaned", "", True)
    return OwnerAnswer(holder.owner, holder.origin, holder.evidence, holder.start_known)
