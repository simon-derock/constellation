import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from constellation.live.pseudonyms import is_bot, pseudonym

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TITLE_MAX = 200


@dataclass(frozen=True, slots=True)
class Item:
    # people appear only as aliases, and no issue body is ever read: only what a public title and state say
    doc_id: str
    repo: str
    number: int
    kind: str
    title: str
    author: str | None
    assignees: tuple[str, ...]
    labels: tuple[str, ...]
    state: str
    created_at: int
    closed_at: int | None
    updated_at: int


@dataclass(frozen=True, slots=True)
class Claim:
    kid: str
    item: str
    predicate: str
    value: str
    valid_from: int
    valid_to: int | None
    # derived: reconstructed from the source's own timestamps; observed: dated by when a sync saw it
    origin: str
    supersedes: str | None


@dataclass(frozen=True, slots=True)
class Fact:
    item: str
    predicate: str
    value: str
    # when a transition to this value is known to have happened; absent when only a sync could date it
    transition_at: int | None


@dataclass(frozen=True, slots=True)
class Change:
    item: str
    predicate: str
    old: str
    new: str
    at: int


@dataclass(frozen=True, slots=True)
class Plan:
    new_claims: list[Claim]
    closures: list[tuple[str, int]]
    changes: list[Change]


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def item_from_github(repo: str, raw: Mapping[str, Any], key: str) -> Item | None:
    # automation and deleted accounts are not people: their items are not part of the company's knowledge
    if is_bot(raw.get("user")):
        return None
    pull = raw.get("pull_request")
    merged = isinstance(pull, Mapping) and bool(pull.get("merged_at"))
    state = "open" if raw["state"] == "open" else "merged" if merged else "closed"
    closed = raw.get("closed_at")
    return Item(
        doc_id=f"{repo}#{raw['number']}",
        repo=repo,
        number=int(raw["number"]),
        kind="pr" if pull is not None else "issue",
        title=_CONTROL.sub("", str(raw["title"]))[:_TITLE_MAX],
        author=pseudonym(raw["user"]["login"], key),
        assignees=tuple(
            sorted(pseudonym(a["login"], key) for a in raw.get("assignees") or [] if not is_bot(a)),
        ),
        labels=tuple(sorted(str(label["name"]) for label in raw.get("labels") or [])),
        state=state,
        created_at=_epoch(raw["created_at"]),
        closed_at=_epoch(closed) if closed else None,
        updated_at=_epoch(raw["updated_at"]),
    )


def facts_of(item: Item, observed_at: int) -> list[Fact]:
    del observed_at  # the facts themselves are timeless; the plan dates what only a sync could date
    transition = item.closed_at if item.state != "open" else None
    return [
        Fact(item.doc_id, "state", item.state, transition),
        Fact(item.doc_id, "assignees", ",".join(item.assignees), None),
        Fact(item.doc_id, "labels", ",".join(item.labels), None),
    ]


def _kid(item: str, predicate: str, value: str, valid_from: int) -> str:
    return hashlib.sha1(f"{item}|{predicate}|{value}|{valid_from}".encode(), usedforsecurity=False).hexdigest()[:16]


def _claim(
    fact: Fact,
    value: str,
    start: int,
    end: int | None,
    origin: str,
    supersedes: str | None = None,
    anchor: int | None = None,
) -> Claim:
    # the id is anchored to a time the source itself states when there is one, never to when a sync happened to run
    ident = _kid(fact.item, fact.predicate, value, start if anchor is None else anchor)
    return Claim(ident, fact.item, fact.predicate, value, start, end, origin, supersedes)


def _first_sight(item: Item, fact: Fact, observed_at: int) -> list[Claim]:
    if fact.predicate != "state":
        # an empty assignee or label list at first sight says nothing, so no claim is invented for it
        return [_claim(fact, fact.value, observed_at, None, "observed", anchor=item.created_at)] if fact.value else []
    if fact.value == "open":
        return [_claim(fact, "open", item.created_at, None, "derived")]
    ended = fact.transition_at if fact.transition_at is not None else observed_at
    opened = _claim(fact, "open", item.created_at, ended, "derived")
    return [opened, _claim(fact, fact.value, ended, None, "derived", supersedes=opened.kid)]


def plan_changes(existing: Mapping[tuple[str, str], Claim], items: Iterable[Item], observed_at: int) -> Plan:
    # history reconstructed on first sight is not a change; a difference from a stored open claim always is, and it
    # closes the old claim, opens the new one and links them, so nothing is ever overwritten
    new_claims: list[Claim] = []
    closures: list[tuple[str, int]] = []
    changes: list[Change] = []
    for item in items:
        for fact in facts_of(item, observed_at):
            current = existing.get((fact.item, fact.predicate))
            if current is None:
                new_claims.extend(_first_sight(item, fact, observed_at))
            elif current.value != fact.value:
                at = fact.transition_at if fact.transition_at is not None else observed_at
                origin = "derived" if fact.transition_at is not None else "observed"
                closures.append((current.kid, at))
                new_claims.append(_claim(fact, fact.value, at, None, origin, supersedes=current.kid))
                changes.append(Change(fact.item, fact.predicate, current.value, fact.value, at))
    return Plan(new_claims, closures, changes)
