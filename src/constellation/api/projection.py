from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

_MAX_NODES = 700
_MAX_EDGES = 1_000

# colours are chosen per layer by the theme, so a type maps to a layer and never to a colour
_LAYER = {
    "Person": "identity",
    "Domain": "product",
    "Repo": "product",
    "Role": "financial",
    "Event": "commerce",
    "Artifact": "evidence",
}

type Row = Sequence[Any]


@dataclass(frozen=True, slots=True)
class View:
    id: str
    tenant: Literal["apex", "live"]
    title: str
    hint: str
    # catalogue queries run in order; each returns edges as (sid, stype, slabel, tid, ttype, tlabel, rel)
    steps: tuple[tuple[str, dict[str, int]], ...]


VIEWS: tuple[View, ...] = (
    View(
        "apex-organisation",
        "apex",
        "Who owns what",
        "People, the domains they own, their roles and who they escalate to",
        (("graph_apex_ownership", {}), ("graph_apex_roles", {}), ("graph_apex_escalation", {})),
    ),
    View(
        "apex-causal",
        "apex",
        "What caused what",
        "Events in the first eight days and the causal links between them",
        (("graph_apex_causal", {"from": 0, "to": 8, "limit": 260}),),
    ),
    View(
        "live-network",
        "live",
        "Who works with whom",
        "The most connected people in FalkorDB's GitHub, linked by shared repositories",
        (("graph_live_network", {"people": 100, "limit": 700}),),
    ),
    View(
        "live-repos",
        "live",
        "Where people work",
        "The busiest repositories and the people active in them",
        (("graph_live_repos", {"repos": 10}),),
    ),
)


def view_by_id(view_id: str) -> View:
    for view in VIEWS:
        if view.id == view_id:
            return view
    raise KeyError(view_id)


def build_graph(rows: Sequence[Row]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # nodes and edges come only from the rows the graph returned; a node's weight is how many edges touch it
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for sid, stype, slabel, tid, ttype, tlabel, rel in rows:
        for key, kind, label in ((sid, stype, slabel), (tid, ttype, tlabel)):
            node_id = f"{kind}:{key}"
            nodes.setdefault(
                node_id,
                {
                    "id": node_id,
                    "type": kind,
                    "layer": _LAYER.get(str(kind), "intelligence"),
                    "label": str(label),
                    "weight": 0,
                    "source_count": 0,
                    "confidence": 1.0,
                    "privacy_state": "public",
                    "scope": "graph",
                },
            )
        edge_id = f"{rel}:{stype}:{sid}>{ttype}:{tid}"
        if edge_id in edges:
            continue
        edges[edge_id] = {
            "id": edge_id,
            "source": f"{stype}:{sid}",
            "target": f"{ttype}:{tid}",
            "relationship_type": str(rel),
            "confidence": 1.0,
            "provenance_label": "FalkorDB",
        }
        nodes[f"{stype}:{sid}"]["weight"] += 1
        nodes[f"{ttype}:{tid}"]["weight"] += 1
    for node in nodes.values():
        node["source_count"] = node["weight"]
    if len(nodes) > _MAX_NODES or len(edges) > _MAX_EDGES:
        raise ValueError("this projection is too large to draw")
    return list(nodes.values()), list(edges.values())
