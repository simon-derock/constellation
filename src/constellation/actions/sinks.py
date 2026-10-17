import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol

type Transport = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, Any]]]

_ORIGIN = "https://api.github.com/"
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_LABEL = "agent-action"
_TITLE_MAX = 200
_BODY_MAX = 4_000


class SinkError(Exception):
    pass


class Sink(Protocol):
    def execute(self, action: Mapping[str, Any]) -> dict[str, object]: ...


def github_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    # only the provider's https origin is ever opened, so file:// and other schemes cannot be
    if not url.startswith(_ORIGIN):
        raise SinkError("refusing to open a URL outside the provider origin")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}


def _checked(repo: str) -> str:
    # the pattern allows dots inside names, so dot-only segments are refused separately: they would climb the URL path
    if not _REPO.fullmatch(repo) or any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError(f"invalid repository {repo!r}: expected owner/name")
    return repo


class DryRunSink:
    # records what an approved action would do, and does nothing: the safe mode anyone may approve
    def __init__(self, repo: str) -> None:
        self._repo = _checked(repo)

    def execute(self, action: Mapping[str, Any]) -> dict[str, object]:
        return {
            "dry_run": True,
            "would_create": {"repo": self._repo, "title": str(action["title"])[:_TITLE_MAX], "labels": [_LABEL]},
        }


class GitHubIssueSink:
    # files one labelled issue in one repository; the token is fine-grained to issues on that repository alone
    def __init__(self, repo: str, token: str, transport: Transport = github_post) -> None:
        self._repo, self._token, self._transport = _checked(repo), token, transport

    def execute(self, action: Mapping[str, Any]) -> dict[str, object]:
        marker = f"\n\n<!-- agent-action id {action['id']} -->"
        payload = {
            "title": str(action["title"])[:_TITLE_MAX],
            "body": str(action["body"])[: _BODY_MAX - len(marker)] + marker,
            "labels": [_LABEL],
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        status, body = self._transport(f"{_ORIGIN}repos/{self._repo}/issues", headers, json.dumps(payload).encode())
        if status != 201:
            # the provider's message describes the request; the token is never part of it
            raise SinkError(f"GitHub refused the issue (HTTP {status}): {str(body.get('message', ''))[:120]}")
        return {"dry_run": False, "url": str(body["html_url"]), "number": int(body["number"])}
