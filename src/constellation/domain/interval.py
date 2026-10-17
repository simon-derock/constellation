from collections.abc import Iterable
from dataclasses import dataclass


# one ordinal per clock: simulation day for Apex, epoch seconds for live tenants; never mixed in one graph
@dataclass(frozen=True, slots=True)
class Interval:
    # half-open [start, end): on a handover tick the new holder answers; end None means still open
    start: int
    end: int | None = None

    def __post_init__(self) -> None:
        # an empty interval asserts nothing, so it is a defect at the source, not a value to store
        if self.end is not None and self.end <= self.start:
            raise ValueError(f"empty interval [{self.start}, {self.end})")

    def contains(self, t: int) -> bool:
        return self.start <= t and (self.end is None or t < self.end)

    def overlaps(self, other: "Interval") -> bool:
        return (self.end is None or other.start < self.end) and (other.end is None or self.start < other.end)

    def close_at(self, t: int) -> "Interval":
        # supersession closes the old interval; history is never rewritten in place
        if self.end is not None:
            raise ValueError(f"already closed at {self.end}")
        if t <= self.start:
            raise ValueError(f"close tick {t} must come after start {self.start}")
        return Interval(self.start, t)


def holder_at[T](holdings: Iterable[tuple[T, Interval]], t: int) -> T | None:
    # exclusive roles (owner, assignee) admit one holder per tick; two means the source data is wrong
    holders = [who for who, iv in holdings if iv.contains(t)]
    if len(holders) > 1:
        raise ValueError(f"{len(holders)} holders at tick {t}")
    return holders[0] if holders else None
