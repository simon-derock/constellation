import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# "Path: Chloe (Engineering_Mobile Lead) -> Sarah (Product Lead) -- 1 hop(s)" → Chloe, Sarah
_PATH = re.compile(r"Path:\s*(.*?)(?:\s+--\s|$)")
_ROLE = re.compile(r"\s*\(.*\)\s*$")


@dataclass(frozen=True, slots=True)
class Chain:
    # escalation order: path[0] escalates to path[1], and on up
    path: tuple[str, ...]
    day: int
    evidence: str


def chain_from_facts(facts: Mapping[str, object], day: int, evidence: str) -> Chain | None:
    detail = facts.get("chain_detail")
    names: list[str] = []
    if isinstance(detail, list):
        names = [str(hop[0]) for hop in detail if isinstance(hop, list) and hop]
    else:
        note = facts.get("new_path_note")
        match = _PATH.search(note) if isinstance(note, str) else None
        if match:
            names = [n for n in (_ROLE.sub("", hop).strip() for hop in match.group(1).split("->")) if n]
    # one person is not an escalation; a malformed record is dropped rather than guessed
    return Chain(tuple(names), day, evidence) if len(names) >= 2 else None


def path_as_of(chains: Iterable[Chain], person: str, day: int) -> Chain | None:
    # an observed path stays current until the same person is observed escalating differently
    seen = [c for c in chains if c.path[0] == person and c.day <= day]
    return max(seen, key=lambda c: (c.day, c.evidence), default=None)
