from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from constellation.api.catalogue import Day, EventId, Name, Proof, prove
from constellation.graph.read import ReadPort

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def build_server(port: ReadPort, graph: str) -> FastMCP:
    # the graph is bound here, from the authenticated tenant, never chosen by a tool argument
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

    return mcp
