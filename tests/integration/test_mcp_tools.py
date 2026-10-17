import asyncio
from pathlib import Path
from typing import Any

import pytest
from falkordb import FalkorDB
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from constellation.api.mcp import build_server
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.ingest.build_apex import build

pytestmark = pytest.mark.integration
GRAPH = "brain:apex-mcp"
TOOLS = {"who_could_see", "owner_as_of", "counterfactual", "absence", "escalation_path"}


@pytest.fixture(scope="module")
def server(falkordb: FalkorDB) -> FastMCP:
    if not Path("data/raw/apex").exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, Path("data/raw/apex"), Path("pins/datasets.json"))
    return build_server(ReadPort(falkordb), GRAPH)


def call(server: FastMCP, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(server) as client:
            result = await client.call_tool(tool, args)
            assert isinstance(result.structured_content, dict)
            return result.structured_content

    return asyncio.run(run())


def tools(server: FastMCP) -> list[Any]:
    async def run() -> list[Any]:
        async with Client(server) as client:
            return list(await client.list_tools())

    return asyncio.run(run())


@pytest.mark.ac("AC-T1-02")
def test_every_catalogue_capability_is_a_tool(server: FastMCP) -> None:
    assert {t.name for t in tools(server)} == TOOLS


@pytest.mark.ac("AC-INV-06")
def test_every_tool_is_declared_read_only_and_cannot_choose_its_graph(server: FastMCP) -> None:
    for tool in tools(server):
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name
        assert not {"graph", "cypher", "query"} & set(tool.input_schema["properties"]), tool.name
        assert tool.description, tool.name


@pytest.mark.ac("AC-INV-03")
def test_a_tool_answer_is_a_replayable_proof(falkordb: FalkorDB, server: FastMCP) -> None:
    answer = call(server, "owner_as_of", {"domain": "Project Titan", "day": 30})
    assert answer["query"] == "owner_as_of"
    assert answer["rows"][0][0] == "Sam"
    direct = ReadPort(falkordb).run(GRAPH, cypher("owner_as_of"), {"domain": "Project Titan", "day": 30})
    assert answer["sha256"] == direct.sha256


def test_absence_answers_carry_the_searched_space(server: FastMCP) -> None:
    answer = call(server, "absence", {"trigger": "EVT-8-incident_opened-1219", "response_type": "postmortem_created"})
    assert answer["columns"] == ["responded", "response_event", "searched"]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("owner_as_of", {"domain": "Project Titan", "day": 10**9}),
        ("owner_as_of", {"domain": "x" * 500, "day": 1}),
        ("who_could_see", {"actor": "", "day": 1}),
        ("owner_as_of", {"domain": "Project Titan"}),
    ],
)
def test_out_of_bounds_input_is_refused_before_the_graph(server: FastMCP, tool: str, args: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        call(server, tool, args)
