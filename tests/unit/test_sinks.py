import json
from typing import Any

import pytest

from constellation.actions.sinks import DryRunSink, GitHubIssueSink, SinkError

ACTION = {"kind": "file_issue", "title": "Ownership gap: kubernetes-deploy", "body": "Evidence hash abc", "id": "a1b2"}


class Recorder:
    def __init__(self, status: int = 201, body: dict[str, Any] | None = None) -> None:
        self.status, self.body = status, body or {"html_url": "https://github.com/o/r/issues/7", "number": 7}
        self.calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(self, url: str, headers: dict[str, str], payload: bytes) -> tuple[int, dict[str, Any]]:
        self.calls.append((url, headers, json.loads(payload)))
        return self.status, self.body


def test_a_dry_run_describes_what_would_happen_and_does_nothing() -> None:
    result = DryRunSink("o/r").execute(ACTION)
    assert result["dry_run"] is True
    assert result["would_create"] == {"repo": "o/r", "title": ACTION["title"], "labels": ["agent-action"]}


def test_the_github_sink_files_a_labelled_issue_and_returns_its_link() -> None:
    transport = Recorder()
    result = GitHubIssueSink("o/r", "secret-token", transport=transport).execute(ACTION)
    url, headers, payload = transport.calls[0]
    assert url == "https://api.github.com/repos/o/r/issues"
    assert headers["Authorization"] == "Bearer secret-token"
    assert payload["labels"] == ["agent-action"]
    assert payload["title"] == ACTION["title"]
    assert "agent-action id a1b2" in payload["body"]
    assert result == {"dry_run": False, "url": "https://github.com/o/r/issues/7", "number": 7}


def test_failures_never_carry_the_token() -> None:
    sink = GitHubIssueSink("o/r", "secret-token", transport=Recorder(status=403, body={"message": "Bad credentials"}))
    with pytest.raises(SinkError) as err:
        sink.execute(ACTION)
    assert "secret-token" not in str(err.value)
    assert "403" in str(err.value)


@pytest.mark.parametrize("repo", ["", "owner", "a/b/c", "../x", "./x", "o/..", "o/.", "o/r; rm", "o/ r", "o/r\n"])
def test_a_repository_name_that_could_change_the_request_path_is_refused(repo: str) -> None:
    with pytest.raises(ValueError, match="repository"):
        GitHubIssueSink(repo, "t")


def test_titles_and_bodies_are_bounded_before_they_leave() -> None:
    transport = Recorder()
    big = {**ACTION, "title": "t" * 500, "body": "b" * 9_000}
    GitHubIssueSink("o/r", "t", transport=transport).execute(big)
    payload = transport.calls[0][2]
    assert len(payload["title"]) <= 200
    assert len(payload["body"]) <= 4_000
