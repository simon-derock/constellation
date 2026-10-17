import asyncio
import json
from pathlib import Path
from typing import Any

from constellation.api.mcp import build_server
from constellation.graph.read import ReadPort

# the MCP contract is public API: any change must arrive as a reviewed diff of this snapshot
SNAPSHOT = Path("tests/snapshots/mcp_tools.json")


class _NoGraph(ReadPort):
    # listing tools never touches the graph
    def __init__(self) -> None:
        pass


def contract() -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        tools = await build_server(_NoGraph(), "brain:none").list_tools()
        return sorted(
            (
                {
                    "name": t.name,
                    "description": t.description,
                    "input": t.parameters,
                    "read_only": bool(t.annotations and t.annotations.read_only_hint),
                }
                for t in tools
            ),
            key=lambda t: t["name"],
        )

    return asyncio.run(run())


def test_tool_contract_matches_the_snapshot() -> None:
    assert contract() == json.loads(SNAPSHOT.read_text())
