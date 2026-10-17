import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from constellation.brain.access import SimEvent


@dataclass(frozen=True, slots=True)
class ApexArtifact:
    doc_id: str
    kind: str
    day: int
    title: str
    body: str


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
