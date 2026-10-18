from typing import Any

import pytest

from constellation.live.github import GitHubClient, RateLimitedError, SourceError, github_get


def page(
    items: list[dict[str, object]], next_url: str | None = None, etag: str = "e1", status: int = 200
) -> tuple[int, dict[str, str], Any]:
    link = f'<{next_url}>; rel="next", <https://api.github.com/x>; rel="last"' if next_url else ""
    return status, {"link": link, "etag": etag, "x-ratelimit-remaining": "4000"}, items


class Fake:
    def __init__(self, *responses: tuple[int, dict[str, str], object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], object]:
        self.calls.append((url, headers))
        return self.responses.pop(0)


def test_repositories_skip_forks_and_archived_ones() -> None:
    raw = [
        {"full_name": "o/a", "fork": False, "archived": False},
        {"full_name": "o/b", "fork": True, "archived": False},
        {"full_name": "o/c", "fork": False, "archived": True},
    ]
    client = GitHubClient("t", Fake(page(raw)))
    assert client.repositories("o") == ["o/a"]


def test_pagination_follows_the_link_header_to_the_end() -> None:
    fake = Fake(page([{"number": 1}], "https://api.github.com/p2"), page([{"number": 2}]))
    got = list(GitHubClient("t", fake).items("o/a", since=None))
    assert [g["number"] for g in got] == [1, 2]
    assert fake.calls[1][0] == "https://api.github.com/p2"


def test_since_and_ascending_update_order_are_requested() -> None:
    fake = Fake(page([]))
    list(GitHubClient("t", fake).items("o/a", since="2026-01-01T00:00:00Z"))
    url = fake.calls[0][0]
    assert "since=2026-01-01T00%3A00%3A00Z" in url
    assert "sort=updated" in url
    assert "direction=asc" in url
    assert "state=all" in url


def test_the_token_is_sent_as_a_bearer_header_and_nowhere_else() -> None:
    fake = Fake(page([]))
    list(GitHubClient("secret-token", fake).items("o/a", since=None))
    url, headers = fake.calls[0]
    assert headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in url


def test_a_not_modified_answer_yields_nothing_and_etags_are_reused() -> None:
    fake = Fake(page([{"number": 1}], etag="abc"), (304, {"etag": "abc"}, None))
    client = GitHubClient("t", fake)
    assert len(list(client.items("o/a", since=None))) == 1
    assert list(client.items("o/a", since=None)) == []
    assert fake.calls[1][1]["If-None-Match"] == "abc"


def test_rate_limit_is_a_distinct_error_carrying_the_reset_time() -> None:
    limited = (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}, {"message": "rate limit"})
    with pytest.raises(RateLimitedError) as err:
        list(GitHubClient("t", Fake(limited)).items("o/a", since=None))
    assert err.value.reset == 1790000000


def test_other_failures_never_echo_the_token() -> None:
    with pytest.raises(SourceError) as err:
        list(GitHubClient("secret-token", Fake((500, {}, {"message": "boom"}))).items("o/a", since=None))
    assert "secret-token" not in str(err.value)
    assert "500" in str(err.value)


@pytest.mark.parametrize("repo", ["../x", "o/..", "o", "o/a/b", "o/a?x=1", ""])
def test_malformed_repository_names_are_refused_before_any_request(repo: str) -> None:
    fake = Fake()
    with pytest.raises(ValueError, match="repository"):
        list(GitHubClient("t", fake).items(repo, since=None))
    assert fake.calls == []


def test_a_next_link_outside_the_provider_origin_is_not_followed() -> None:
    fake = Fake(page([{"number": 1}], "https://evil.example/p2"))
    with pytest.raises(SourceError, match="origin"):
        list(GitHubClient("t", fake).items("o/a", since=None))


def test_the_real_transport_refuses_other_origins() -> None:
    with pytest.raises(SourceError, match="origin"):
        github_get("file:///etc/passwd", {})
