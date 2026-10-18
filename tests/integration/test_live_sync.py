from typing import Any

import pytest
from falkordb import FalkorDB

from constellation.graph.write import WritePort
from constellation.live.github import GitHubClient
from constellation.live.graph import LiveGraph
from constellation.live.sync import Syncer

pytestmark = pytest.mark.integration
GRAPH = "brain:live-sync-test"
KEY = "k" * 32


def issue(
    number: int, state: str = "open", updated: str = "2026-01-01T00:00:00Z", login: str = "alice"
) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"item {number}",
        "state": state,
        "user": {"login": login, "type": "User"},
        "assignees": [],
        "labels": [],
        "created_at": "2025-12-01T00:00:00Z",
        "updated_at": updated,
        "closed_at": "2026-01-01T00:00:00Z" if state == "closed" else None,
    }


class World:
    # a tiny stand-in for the provider: one organisation, repositories with issue lists, honouring `since`
    def __init__(self) -> None:
        self.repos: dict[str, list[dict[str, Any]]] = {"o/a": [issue(1), issue(2)], "o/b": [issue(3)]}
        self.requests: list[str] = []
        self.limited = False

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], Any]:
        self.requests.append(url)
        if self.limited:
            return 403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}, {}
        if "/orgs/o/repos" in url:
            return 200, {}, [{"full_name": name, "fork": False, "archived": False} for name in self.repos]
        name = url.split("/repos/")[1].split("/issues")[0]
        since = url.split("since=")[1].split("&")[0].replace("%3A", ":") if "since=" in url else ""
        return 200, {}, [i for i in self.repos[name] if i["updated_at"] >= since]


@pytest.fixture
def parts(falkordb: FalkorDB) -> tuple[World, LiveGraph, Syncer]:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    world, graph = World(), LiveGraph(falkordb, WritePort(falkordb), GRAPH)
    return world, graph, Syncer(GitHubClient("t", world), graph, KEY, clock=lambda: 1_790_000_000)


def test_a_first_sync_loads_every_repository_and_advances_the_cursors(parts: tuple[World, LiveGraph, Syncer]) -> None:
    _, graph, syncer = parts
    report = syncer.run("o")
    assert (report.repositories, report.items, report.rate_limited) == (2, 3, False)
    assert graph.query("MATCH (i:Item) RETURN count(i)") == [[3]]
    assert graph.cursor("o/a") == "2026-01-01T00:00:00Z"


def test_a_second_sync_sees_only_what_changed_and_reports_it(parts: tuple[World, LiveGraph, Syncer]) -> None:
    world, graph, syncer = parts
    syncer.run("o")
    world.repos["o/a"][0] = issue(1, state="closed", updated="2026-02-01T00:00:00Z")
    report = syncer.run("o")
    assert report.changes == 1
    assert graph.query("MATCH (c:Change {predicate: 'state'}) RETURN c.old, c.new") == [["open", "closed"]]
    assert graph.cursor("o/a") == "2026-02-01T00:00:00Z"


def test_hitting_the_rate_limit_stops_cleanly_and_keeps_earlier_progress(
    parts: tuple[World, LiveGraph, Syncer],
) -> None:
    world, graph, syncer = parts
    syncer.run("o")
    world.repos["o/a"].append(issue(9, updated="2026-03-01T00:00:00Z"))
    world.limited = True
    report = syncer.run("o")
    assert report.rate_limited is True
    assert report.retry_at == 1790000000
    assert graph.query("MATCH (i:Item) RETURN count(i)") == [[3]]
    world.limited = False
    # `since` is inclusive, so boundary items are seen again; replaying them must change nothing
    report = syncer.run("o")
    assert report.changes == 0
    assert graph.query("MATCH (i:Item {number: 9}) RETURN count(i)") == [[1]]


def test_bot_items_never_reach_the_graph(parts: tuple[World, LiveGraph, Syncer]) -> None:
    world, graph, syncer = parts
    world.repos["o/a"].append({**issue(5), "user": {"login": "dependabot[bot]", "type": "Bot"}})
    syncer.run("o")
    assert graph.query("MATCH (i:Item {number: 5}) RETURN count(i)") == [[0]]
