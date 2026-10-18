import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

type Transport = Callable[[str, dict[str, str]], tuple[int, dict[str, str], Any]]

_ORIGIN = "https://api.github.com/"
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_OWNER = re.compile(r"[A-Za-z0-9_.-]+")
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
_PAGE_LIMIT = 200


class SourceError(Exception):
    pass


class RateLimitedError(SourceError):
    def __init__(self, reset: int) -> None:
        super().__init__(f"GitHub rate limit reached; resets at {reset}")
        self.reset = reset


def github_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], Any]:
    # only the provider's https origin is ever opened, so file:// and other schemes cannot be
    if not url.startswith(_ORIGIN):
        raise SourceError("refusing to open a URL outside the provider origin")
    request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            return response.status, {k.lower(): v for k, v in response.headers.items()}, json.load(response)
    except urllib.error.HTTPError as err:
        raw = err.read() or b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        return err.code, {k.lower(): v for k, v in err.headers.items()}, body


def _repo(name: str) -> str:
    # the pattern allows dots inside names, so dot-only segments are refused separately: they would climb the URL path
    if not _REPO.fullmatch(name) or any(part in {".", ".."} for part in name.split("/")):
        raise ValueError(f"invalid repository {name!r}: expected owner/name")
    return name


class GitHubClient:
    # reads public metadata only; a 304 costs no rate limit, so an idle sync is nearly free
    def __init__(self, token: str, transport: Transport = github_get) -> None:
        self._token, self._transport = token, transport
        self._etags: dict[str, str] = {}

    def _headers(self, url: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if url in self._etags:
            headers["If-None-Match"] = self._etags[url]
        return headers

    def _pages(self, first: str) -> Iterator[list[dict[str, Any]]]:
        url: str | None = first
        for _ in range(_PAGE_LIMIT):
            if url is None:
                return
            if not url.startswith(_ORIGIN):
                raise SourceError("refusing to follow a link outside the provider origin")
            status, headers, body = self._transport(url, self._headers(url))
            if status == 304:
                return
            if status in (403, 429) and headers.get("x-ratelimit-remaining") == "0":
                raise RateLimitedError(int(headers.get("x-ratelimit-reset", "0")))
            if status != 200:
                # the provider's message describes the request; the token is never part of it
                raise SourceError(f"GitHub answered HTTP {status}: {str((body or {}).get('message', ''))[:120]}")
            if "etag" in headers:
                self._etags[url] = headers["etag"]
            yield list(body)
            match = _NEXT.search(headers.get("link", ""))
            url = match.group(1) if match else None
        raise SourceError("pagination did not end")

    def repositories(self, org: str) -> list[str]:
        if not _OWNER.fullmatch(org) or org in {".", ".."}:
            raise ValueError(f"invalid organisation {org!r}")
        found: list[str] = []
        for batch in self._pages(f"{_ORIGIN}orgs/{org}/repos?type=public&per_page=100"):
            found.extend(str(r["full_name"]) for r in batch if not r.get("fork") and not r.get("archived"))
        return found

    def items(self, repo: str, since: str | None) -> Iterator[dict[str, Any]]:
        # issues and pull requests share one endpoint; ascending by update time lets a cursor advance safely
        query = {"state": "all", "sort": "updated", "direction": "asc", "per_page": "100"}
        if since:
            query["since"] = since
        for batch in self._pages(f"{_ORIGIN}repos/{_repo(repo)}/issues?{urllib.parse.urlencode(query)}"):
            yield from batch
