import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from constellation.api.mcp import Principal, build_server
from constellation.graph.read import ReadPort
from constellation.memory.store import MemoryStore

# the MCP contract is public API: any change must arrive as a reviewed diff of these snapshots
SNAPSHOT = Path("tests/snapshots/mcp_tools.json")
MEMORY_SNAPSHOT = Path("tests/snapshots/mcp_memory_tools.json")


class _NoGraph(ReadPort):
    # listing tools never touches the graph
    def __init__(self) -> None:
        pass


def _no_db_store() -> MemoryStore:
    # listing tools and checking names never touch the database
    return MemoryStore(None, tenant="t0")


def contract(memory: MemoryStore | None = None) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        server = build_server(_NoGraph(), "brain:none", live_graph="brain:none-live", memory=memory)
        return sorted(
            (
                {
                    "name": t.name,
                    "description": t.description,
                    "input": t.parameters,
                    "read_only": bool(t.annotations and t.annotations.read_only_hint),
                }
                for t in await server.list_tools()
            ),
            key=lambda t: t["name"],
        )

    return asyncio.run(run())


@pytest.mark.ac("AC-T1-02")
def test_tool_contract_matches_the_snapshot() -> None:
    assert contract() == json.loads(SNAPSHOT.read_text())


@pytest.mark.ac("AC-T1-02")
def test_memory_tools_only_add_to_the_contract_and_match_their_snapshot() -> None:
    base, full = contract(), contract(_no_db_store())
    assert [t for t in full if t in base] == base
    assert [t for t in full if t not in base] == json.loads(MEMORY_SNAPSHOT.read_text())


@pytest.mark.parametrize(
    "name", ["", "a", "A", "a:b", "a b", "-a", "_a", "a-b_c", "a" * 63, "a" * 64, "a\n", "mem:t:a", "é", "a.b"]
)
def test_the_principal_schema_accepts_exactly_what_the_store_accepts(name: str) -> None:
    try:
        _no_db_store().graph_name(name)
        stored = True
    except ValueError:
        stored = False
    try:
        TypeAdapter(Principal).validate_python(name)
        schema = True
    except ValidationError:
        schema = False
    assert schema == stored
