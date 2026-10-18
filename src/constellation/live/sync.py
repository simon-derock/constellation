from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from constellation.live.github import GitHubClient, RateLimitedError
from constellation.live.graph import LiveGraph
from constellation.live.model import item_from_github, plan_changes


@dataclass(frozen=True, slots=True)
class SyncReport:
    repositories: int
    items: int
    changes: int
    rate_limited: bool
    retry_at: int | None


class Syncer:
    # one repository at a time, cursor saved after each, so a rate limit or a crash costs only the repository in flight
    def __init__(self, client: GitHubClient, graph: LiveGraph, key: str, clock: Callable[[], int]) -> None:
        self._client, self._graph, self._key, self._clock = client, graph, key, clock

    def _one(self, repo: str) -> tuple[int, int]:
        raw: list[dict[str, Any]] = list(self._client.items(repo, self._graph.cursor(repo)))
        if not raw:
            return 0, 0
        items = [i for r in raw if (i := item_from_github(repo, r, self._key)) is not None]
        plan = plan_changes(self._graph.open_claims(repo), items, observed_at=self._clock())
        self._graph.apply(items, plan)
        # sorted ascending by update time, so the last is the newest; bot items still advance the cursor
        self._graph.set_cursor(repo, max(str(r["updated_at"]) for r in raw))
        return len(items), len(plan.changes)

    def run(self, org: str) -> SyncReport:
        done = items = changes = 0
        try:
            for repo in self._client.repositories(org):
                n, c = self._one(repo)
                done, items, changes = done + 1, items + n, changes + c
        except RateLimitedError as err:
            return SyncReport(done, items, changes, True, err.reset)
        return SyncReport(done, items, changes, False, None)
