from typing import Annotated, Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from constellation.api.catalogue import Day, EventId, Name, Proof, prove
from constellation.graph.read import ReadPort
from constellation.live.embed import Embedder
from constellation.live.search import hybrid_search

Alias = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[a-z0-9-]+$", description="a person's alias")]
Limit = Annotated[int, Field(ge=1, le=50)]
Epoch = Annotated[int, Field(ge=0, le=4_102_444_800, description="epoch seconds")]
Question = Annotated[str, Field(min_length=1, max_length=200)]

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def build_server(
    port: ReadPort, graph: str, live_graph: str | None = None, embedder: Embedder | None = None
) -> FastMCP:
    # the graphs are bound here, from the authenticated tenants, never chosen by a tool argument
    mcp = FastMCP("constellation")

    @mcp.tool(
        annotations=READ_ONLY,
        description="Artifacts inside an actor's visibility cone on a simulation day: what they could have known.",
    )
    def who_could_see(actor: Name, day: Day) -> Proof:
        return prove(port, graph, "apex_cone", {"actor": actor, "day": day})

    @mcp.tool(
        annotations=READ_ONLY,
        description="Who owned a domain on a simulation day, with origin, evidence and whether the start is known.",
    )
    def owner_as_of(domain: Name, day: Day) -> Proof:
        return prove(port, graph, "owner_as_of", {"domain": domain, "day": day})

    @mcp.tool(
        annotations=READ_ONLY,
        description=(
            "Would removing a cause event have changed an effect event under a causal mechanism? "
            "Returns whether they are linked and any same-mechanism alternative causes."
        ),
    )
    def counterfactual(cause: EventId, effect: EventId, link_type: Name) -> Proof:
        return prove(port, graph, "counterfactual", {"cause": cause, "effect": effect, "link_type": link_type})

    @mcp.tool(
        annotations=READ_ONLY,
        description=(
            "Did an expected response event follow a trigger event? Returns the decision, the response if any, "
            "and the artifact space that was searched."
        ),
    )
    def absence(trigger: EventId, response_type: Name) -> Proof:
        return prove(port, graph, "absence", {"trigger": trigger, "response_type": response_type})

    @mcp.tool(
        annotations=READ_ONLY,
        description="The latest observed escalation path starting at a person on or before a simulation day.",
    )
    def escalation_path(person: Name, day: Day) -> Proof:
        return prove(port, graph, "escalation_path", {"person": person, "day": day})

    if live_graph is not None:
        _live_tools(mcp, port, live_graph, embedder)
    return mcp


def _live_tools(mcp: FastMCP, port: ReadPort, graph: str, embedder: Embedder | None) -> None:
    @mcp.tool(
        annotations=READ_ONLY,
        description=(
            "Search the live GitHub graph by meaning and by words: the engine's HNSW vector index and full-text "
            "index, fused by rank. Every arm that ran comes back as a replayable proof."
        ),
    )
    def live_search(question: Question) -> dict[str, Any]:
        found = hybrid_search(port, graph, question, embedder, k=10)
        return {
            "hits": [{"item": h.item, "title": h.title, "repo": h.repo, "via": list(h.via)} for h in found.hits],
            "vector_used": found.vector_used,
            "proof": found.proof,
        }

    @mcp.tool(
        annotations=READ_ONLY,
        description="PageRank over who collaborates with whom: the most connected people, by alias.",
    )
    def live_central_people(limit: Limit = 10) -> Proof:
        return prove(port, graph, "live_central_people", {"limit": limit})

    @mcp.tool(
        annotations=READ_ONLY,
        description="Betweenness centrality: the people who sit on the most shortest paths between others.",
    )
    def live_bridge_people(limit: Limit = 10) -> Proof:
        return prove(port, graph, "live_bridge_people", {"limit": limit})

    @mcp.tool(
        annotations=READ_ONLY,
        description="The shortest chain of collaborators between two people, as aliases, or empty if unconnected.",
    )
    def live_path(start: Alias, end: Alias) -> Proof:
        return prove(port, graph, "live_path", {"from": start, "to": end})

    @mcp.tool(
        annotations=READ_ONLY,
        description="Every claim ever held about one issue or pull request, with the claim that replaced it.",
    )
    def live_item_history(item: Annotated[str, Field(min_length=3, max_length=120)]) -> Proof:
        return prove(port, graph, "live_item_history", {"item": item})

    @mcp.tool(
        annotations=READ_ONLY,
        description="How many issues and pull requests were open, closed or merged at a past moment.",
    )
    def live_state_as_of(at: Epoch) -> Proof:
        return prove(port, graph, "live_state_as_of", {"at": at})
