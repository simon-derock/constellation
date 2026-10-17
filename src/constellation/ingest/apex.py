import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from constellation.brain.access import SimEvent
from constellation.brain.escalation import Chain, chain_from_facts
from constellation.brain.ownership import Claim, Departure, RegistryEntry


@dataclass(frozen=True, slots=True)
class ApexArtifact:
    doc_id: str
    kind: str
    day: int
    title: str
    body: str


@dataclass(slots=True, eq=False)
class RawEvent:
    # attribute-compatible with orgforge.memory.SimEvent so the vendored causal rules run unmodified
    type: str
    day: int
    date: str
    timestamp: str
    actors: list[str]
    artifact_ids: dict[str, object]
    facts: dict[str, object]
    summary: str
    tags: list[str]
    mongo_id: str


@dataclass(frozen=True, slots=True)
class ApexCorpus:
    events: tuple[SimEvent, ...]
    artifacts: tuple[ApexArtifact, ...]
    roles: dict[str, str]


def parse_artifact_ids(raw: str | None) -> tuple[tuple[str, str], ...]:
    # values are a string or a list of strings; empty values carry no artifact
    if not raw:
        return ()
    pairs: list[tuple[str, str]] = []
    for key, value in json.loads(raw).items():
        values = value if isinstance(value, list) else [value]
        pairs.extend((key, str(v)) for v in values if v)
    return tuple(pairs)


def _role(dept: str) -> str:
    return dept.lower().replace(" ", "_")


def roles_from_config(path: Path) -> dict[str, str]:
    # eval_harness.py ActorVisibilityBuilder._infer_actor_roles; anyone absent is external
    cfg = yaml.safe_load(path.read_text())
    roles = {name: _role(dept) for dept, members in cfg["org_chart"].items() for name in members}
    lifecycle = cfg.get("org_lifecycle") or {}
    for change in (lifecycle.get("scheduled_hires") or []) + (lifecycle.get("scheduled_departures") or []):
        roles[change["name"]] = _role(change["dept"])
    return roles


def _spawned_doc(facts: str | None) -> bool:
    if not facts:
        return False
    parsed = json.loads(facts)
    return isinstance(parsed, dict) and bool(parsed.get("spawned_doc"))


def load_apex(corpus: Path, config: Path) -> ApexCorpus:
    frame = pl.read_parquet(corpus)
    events = tuple(
        SimEvent(
            day=row["day"],
            type=row["doc_type"],
            actors=tuple(json.loads(row["actors"] or "[]")),
            artifact_ids=parse_artifact_ids(row["artifact_ids"]),
            event_id=row["doc_id"],
            spawned_doc=_spawned_doc(row["facts"]),
        )
        for row in frame.filter(pl.col("category") == "sim_event").iter_rows(named=True)
    )
    artifacts = tuple(
        ApexArtifact(row["doc_id"], row["doc_type"], row["day"], row["title"] or "", row["body"] or "")
        for row in frame.filter(pl.col("category") == "artifact").iter_rows(named=True)
    )
    return ApexCorpus(events=events, artifacts=artifacts, roles=roles_from_config(config))


def ownership_sources(corpus: Path, registry: Path) -> tuple[list[RegistryEntry], list[Claim], list[Departure]]:
    # observed sources only: claim and departure events, plus the registry snapshot they must be reconciled with
    entries = [
        RegistryEntry(r["domain"], r["primary_owner"], tuple(r.get("former_owners") or ()), int(r["last_updated_day"]))
        for r in json.loads(registry.read_text())
    ]
    frame = pl.read_parquet(corpus, columns=["doc_id", "doc_type", "category", "day", "facts"])
    events = frame.filter(pl.col("doc_type").is_in(["domain_ownership_claimed", "employee_departed"]))
    claims: list[Claim] = []
    departures: list[Departure] = []
    for row in events.sort("day").iter_rows(named=True):
        facts = json.loads(row["facts"])
        if row["doc_type"] == "domain_ownership_claimed":
            claims.append(Claim(facts["domain"], facts["new_owner"], row["day"], row["doc_id"]))
        else:
            departures.append(Departure(facts["name"], row["day"], row["doc_id"]))
    return entries, claims, departures


def _json_dict(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    value = json.loads(raw)
    return [str(v) for v in value] if isinstance(value, list) else []


def raw_events(corpus: Path) -> list[RawEvent]:
    # chronological: the causal rules return the first matching effect, so order is part of the semantics
    frame = pl.read_parquet(corpus).filter(pl.col("category") == "sim_event").sort(["day", "timestamp"])
    return [
        RawEvent(
            type=row["doc_type"],
            day=row["day"],
            date=row["date"] or "",
            timestamp=row["timestamp"] or "",
            actors=_json_list(row["actors"]),
            artifact_ids=_json_dict(row["artifact_ids"]),
            facts=_json_dict(row["facts"]),
            summary="",
            tags=_json_list(row["tags"]),
            mongo_id=row["doc_id"],
        )
        for row in frame.iter_rows(named=True)
    ]


def escalation_chains(corpus: Path) -> list[Chain]:
    frame = pl.read_parquet(corpus, columns=["doc_id", "doc_type", "day", "facts"])
    rows = frame.filter(pl.col("doc_type") == "escalation_chain").sort("day").iter_rows(named=True)
    chains = (chain_from_facts(_json_dict(r["facts"]), r["day"], r["doc_id"]) for r in rows)
    return [c for c in chains if c is not None]
