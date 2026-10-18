from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from constellation.api.catalogue import Day, EventId, Name, Proof, prove
from constellation.graph.read import ReadPort
from constellation.live.embed import Embedder
from constellation.live.search import hybrid_search
from constellation.memory.store import NAME_PATTERN, SEMANTIC_PREFIX, ConflictError, MemoryStore

Alias = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[a-z0-9-]+$", description="a person's alias")]
Limit = Annotated[int, Field(ge=1, le=50)]
Epoch = Annotated[int, Field(ge=0, le=4_102_444_800, description="epoch seconds")]
Question = Annotated[str, Field(min_length=1, max_length=200)]

# the same rule the store enforces on every graph name; the store re-checks it, so this is the early, readable refusal
Principal = Annotated[
    str,
    Field(
        min_length=1, max_length=63, pattern=f"^{NAME_PATTERN}$", description="whose memory graph: a-z, 0-9, - and _"
    ),
]
FactKey = Annotated[str, Field(min_length=1, max_length=128, description="a fact's name")]
FactValue = Annotated[str, Field(max_length=4_000)]
Task = Annotated[str, Field(min_length=1, max_length=128, description="the task this episode came from")]
Subject = Annotated[
    str, Field(min_length=1, max_length=128, description="what the episode is about; episodes agree only on exact text")
]
Evidence = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=200)]],
    Field(min_length=1, max_length=20, description="ids that support the value: artifact ids, proof hashes"),
]
Version = Annotated[int, Field(ge=0, le=1_000_000_000, description="0 creates; otherwise the version last read")]

# an anonymous caller can address any principal, so the number of graphs it can make is bounded
MAX_PRINCIPALS = 100
# the most evidence ids one learned fact returns; evidence_count says how many there are
MAX_EVIDENCE_SHOWN = 50

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def build_server(
    port: ReadPort,
    graph: str,
    live_graph: str | None = None,
    embedder: Embedder | None = None,
    memory: MemoryStore | None = None,
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
    if memory is not None:
        _memory_tools(mcp, memory)
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


def _has_graph(memory: MemoryStore, principal: str, create: bool) -> bool:
    # a read never makes a graph; a write makes one, up to the cap, so no caller can fill the host with clones
    existing = memory.principals()
    if principal in existing:
        return True
    if not create:
        return False
    if len(existing) >= MAX_PRINCIPALS:
        raise ToolError(f"this server holds at most {MAX_PRINCIPALS} memory graphs; use an existing principal")
    memory.provision(principal)
    return True


def _memory_tools(mcp: FastMCP, memory: MemoryStore) -> None:
    # these write, but only through the store: tenant fixed by the server, graph name validated, every value a parameter
    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
        ),
        description=(
            "Write a fact into a principal's memory by compare-and-set. expected_version 0 creates the fact; "
            "otherwise it must be the version last read. A stale version never overwrites: the result says "
            "ok=false with the current version and value, so the caller can merge and retry. "
            f"Names starting {SEMANTIC_PREFIX!r} belong to consolidation."
        ),
    )
    def remember(principal: Principal, key: FactKey, value: FactValue, expected_version: Version) -> dict[str, Any]:
        if key.startswith(SEMANTIC_PREFIX):
            raise ToolError(f"names starting {SEMANTIC_PREFIX!r} are written only by consolidation")
        _has_graph(memory, principal, create=True)
        try:
            return {"ok": True, "key": key, "version": memory.write_fact(principal, key, value, expected_version)}
        except ConflictError:
            current = memory.read_fact(principal, key)
            version = current.ver if current else 0
            return {
                "ok": False,
                "conflict": True,
                "key": key,
                "expected_version": expected_version,
                "current_version": version,
                "current_value": current.value if current else None,
                "message": f"{key!r} is at version {version}, not {expected_version}: nothing was written",
            }

    @mcp.tool(
        annotations=READ_ONLY,
        description="Read a fact from a principal's memory with its version (found=false, version 0 when absent).",
    )
    def recall(principal: Principal, key: FactKey) -> dict[str, Any]:
        fact = memory.read_fact(principal, key) if _has_graph(memory, principal, create=False) else None
        return {
            "key": key,
            "found": fact is not None,
            "value": fact.value if fact else None,
            "version": fact.ver if fact else 0,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
        ),
        description=(
            "Record what happened on one task: a subject, the value found and the ids of the evidence for it. "
            "Episodes are never changed or removed; learned consolidates them."
        ),
    )
    def record_episode(
        principal: Principal, task: Task, subject: Subject, value: FactValue, evidence: Evidence
    ) -> dict[str, Any]:
        _has_graph(memory, principal, create=True)
        memory.record_episode(principal, task, subject, value, evidence)
        return {"recorded": True, "subject": subject}

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        description=(
            "Consolidate a principal's episodes and return everything it has learned. A subject is learned only "
            "from two or more episodes that agree on the value and none that disagree; each learned fact comes "
            "with the evidence of the agreeing episodes and can be read back with recall under its key."
        ),
    )
    def learned(principal: Principal, limit: Limit = 20) -> dict[str, Any]:
        if not _has_graph(memory, principal, create=False):
            return {"new": [], "facts": [], "truncated": False}
        new = sorted(fact.subject for fact in memory.consolidate(principal))
        facts = memory.semantic_facts(principal)
        return {
            "new": new,
            "truncated": len(facts) > limit,
            "facts": [
                {
                    "key": f"{SEMANTIC_PREFIX}{f.subject}",
                    "subject": f.subject,
                    "value": f.value,
                    "support": f.support,
                    "evidence_count": len(f.evidence),
                    "evidence": list(f.evidence[:MAX_EVIDENCE_SHOWN]),
                }
                for f in facts[:limit]
            ],
        }
