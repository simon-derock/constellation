from constellation.brain.absence import Expectation
from constellation.brain.access import (
    ARTIFACT_SUBSYSTEM,
    BROADCAST_CONFIG,
    ROLE_SUBSYSTEM_ACCESS,
    born_days,
    event_artifacts,
)
from constellation.brain.causality import CausalEdge
from constellation.brain.ownership import OwnershipFact
from constellation.domain.ids import entity_id
from constellation.graph.catalogue import cypher
from constellation.graph.write import WritePort
from constellation.ingest.apex import ApexCorpus

TENANT = "apex"

_ROLES = """UNWIND $rows AS r MERGE (ro:Role {name: r.role})
WITH ro, r UNWIND r.subsystems AS s MERGE (sub:Subsystem {name: s}) MERGE (ro)-[:CAN_OPEN]->(sub)"""
_PEOPLE = """UNWIND $rows AS r MERGE (p:Person {name: r.name}) SET p.id = r.id, p.kind = r.kind
WITH p, r WHERE r.role IS NOT NULL MATCH (ro:Role {name: r.role}) MERGE (p)-[:HAS_ROLE]->(ro)"""
_EVENTS = """UNWIND $rows AS r MERGE (e:Event {eid: r.eid})
SET e.id = r.id, e.day = r.day, e.type = r.type, e.broadcast = r.broadcast"""
_INVOLVED = """UNWIND $rows AS r MATCH (p:Person {name: r.actor}), (e:Event {eid: r.eid})
MERGE (p)-[:INVOLVED_IN]->(e)"""
_ARTIFACTS = """UNWIND $rows AS r MERGE (a:Artifact {doc_id: r.doc_id}) SET a.id = r.id, a.born = r.born"""
_DOCUMENTS = """UNWIND $rows AS r MERGE (a:Artifact {doc_id: r.doc_id})
SET a.id = r.id, a.kind = r.kind, a.title = r.title, a.body = r.body, a.row_day = r.row_day"""
_PRODUCED = """UNWIND $rows AS r MATCH (e:Event {eid: r.eid}), (a:Artifact {doc_id: r.doc_id})
MERGE (e)-[pr:PRODUCED {key: r.key}]->(a) SET pr.subsystem = r.subsystem"""

_CAUSES = """UNWIND $rows AS r MATCH (c:Event {eid: r.cause}), (e:Event {eid: r.effect})
MERGE (c)-[x:CAUSES {link_type: r.link_type}]->(e) SET x.day = r.day"""

_EXPECTS = """UNWIND $rows AS r MATCH (t:Event {eid: r.trigger})
MERGE (x:Expectation {key: r.key}) SET x.response_type = r.response_type, x.responded = r.responded,
x.search_space = r.search_space MERGE (t)-[:EXPECTS]->(x)"""
_MET_BY = """UNWIND $rows AS r MATCH (x:Expectation {key: r.key}), (e:Event {eid: r.response})
MERGE (x)-[:MET_BY]->(e)"""

_OWNS = """UNWIND $rows AS r MERGE (p:Person {name: r.owner}) MERGE (d:Domain {name: r.domain})
MERGE (p)-[o:OWNS {from: r.from}]->(d)
SET o.to = r.to, o.origin = r.origin, o.evidence = r.evidence, o.start_known = r.start_known"""

_INDEXES = (
    ("Person", "name"),
    ("Event", "eid"),
    ("Artifact", "doc_id"),
    ("Role", "name"),
    ("Subsystem", "name"),
)


def cone_query() -> str:
    return cypher("apex_cone")


def load_into(port: WritePort, graph: str, apex: ApexCorpus) -> None:
    # order matters: indexes, then the nodes every relationship MATCHes on
    for label, prop in _INDEXES:
        port.ensure_index(graph, label, prop)
    port.merge(graph, _ROLES, [{"role": r, "subsystems": sorted(s)} for r, s in ROLE_SUBSYSTEM_ACCESS.items() if s])
    actors = sorted({a for e in apex.events for a in e.actors} | set(apex.roles))
    port.merge(
        graph,
        _PEOPLE,
        [
            {
                "name": name,
                "id": str(entity_id(TENANT, "Person", name)),
                "kind": "employee" if name in apex.roles else "external",
                "role": apex.roles.get(name),
            }
            for name in actors
        ],
    )
    port.merge(
        graph,
        _EVENTS,
        [
            {
                "eid": e.event_id,
                "id": str(entity_id(TENANT, "Event", e.event_id)),
                "day": e.day,
                "type": e.type,
                "broadcast": sorted(BROADCAST_CONFIG.get(e.type, frozenset())),
            }
            for e in apex.events
        ],
    )
    port.merge(graph, _INVOLVED, [{"actor": a, "eid": e.event_id} for e in apex.events for a in set(e.actors)])
    born = born_days(apex.events)
    produced_ids = sorted({aid for e in apex.events for aid in event_artifacts(e)})
    port.merge(
        graph,
        _ARTIFACTS,
        [{"doc_id": aid, "id": str(entity_id(TENANT, "Artifact", aid)), "born": born[aid]} for aid in produced_ids],
    )
    port.merge(
        graph,
        _DOCUMENTS,
        [
            {
                "doc_id": a.doc_id,
                "id": str(entity_id(TENANT, "Artifact", a.doc_id)),
                "kind": a.kind,
                "title": a.title,
                "body": a.body,
                "row_day": a.day,
            }
            for a in apex.artifacts
        ],
    )
    port.merge(
        graph,
        _PRODUCED,
        [
            {
                "eid": e.event_id,
                "doc_id": aid,
                "key": key,
                "subsystem": ARTIFACT_SUBSYSTEM.get(key, "default"),
            }
            for e in apex.events
            for key, aid in sorted(set(e.artifact_ids))
            if aid in born
        ],
    )


def load_ownership(port: WritePort, graph: str, facts: list[OwnershipFact]) -> None:
    # an open interval stores no `to`: absent, not a sentinel, so `o.to IS NULL` means "still holds"
    port.ensure_index(graph, "Person", "name")
    port.ensure_index(graph, "Domain", "name")
    port.merge(
        graph,
        _OWNS,
        [
            {
                "owner": f.owner,
                "domain": f.domain,
                "from": f.interval.start,
                "to": f.interval.end,
                "origin": f.origin,
                "evidence": f.evidence,
                "start_known": f.start_known,
            }
            for f in facts
        ],
    )


def load_causes(port: WritePort, graph: str, edges: list[CausalEdge]) -> None:
    # events must already exist: a CAUSES edge never invents its endpoints
    port.ensure_index(graph, "Event", "eid")
    port.merge(
        graph, _CAUSES, [{"cause": e.cause, "effect": e.effect, "link_type": e.link_type, "day": e.day} for e in edges]
    )


def load_expectations(port: WritePort, graph: str, found: list[Expectation]) -> None:
    # search spaces are stored as given: they are what the agent must show it checked
    port.ensure_index(graph, "Expectation", "key")
    rows = [
        {
            "key": f"{x.trigger}|{x.response_type}",
            "trigger": x.trigger,
            "response_type": x.response_type,
            "responded": x.responded,
            "search_space": list(x.search_space),
            "response": x.response_event,
        }
        for x in found
    ]
    port.merge(graph, _EXPECTS, rows)
    port.merge(graph, _MET_BY, [r for r in rows if r["response"] is not None])
