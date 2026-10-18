from pathlib import Path
from typing import Any

import pytest

from constellation.retrieval.rerank import CohereReranker, RerankError, cohere_post

DOCS = [("d1", "alpha text"), ("d2", "beta text"), ("d3", "gamma text")]


class Fake:
    def __init__(self, *replies: tuple[int, dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        import json

        self.calls.append((url, headers, json.loads(body)))
        return self.replies.pop(0)


def ok(*scores: float) -> tuple[int, dict[str, Any]]:
    return 200, {"results": [{"index": i, "relevance_score": s} for i, s in enumerate(scores)]}


def make(fake: Fake, tmp_path: Path, sleeps: list[float] | None = None) -> CohereReranker:
    return CohereReranker(
        "secret-key",
        transport=fake,
        cache_dir=tmp_path,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_documents_come_back_best_first_with_their_ids(tmp_path: Path) -> None:
    got = make(Fake(ok(0.1, 0.9, 0.5)), tmp_path).rerank("q", DOCS, top_n=3)
    assert got == [("d2", 0.9), ("d3", 0.5), ("d1", 0.1)]


def test_equal_scores_keep_the_input_order_so_a_ranking_is_reproducible(tmp_path: Path) -> None:
    got = make(Fake(ok(0.5, 0.5, 0.5)), tmp_path).rerank("q", DOCS, top_n=3)
    assert [d for d, _ in got] == ["d1", "d2", "d3"]


def test_top_n_cuts_the_list(tmp_path: Path) -> None:
    assert [d for d, _ in make(Fake(ok(0.1, 0.9, 0.5)), tmp_path).rerank("q", DOCS, top_n=1)] == ["d2"]


def test_the_same_request_is_never_paid_for_twice(tmp_path: Path) -> None:
    fake = Fake(ok(0.1, 0.9, 0.5))
    first = make(fake, tmp_path).rerank("q", DOCS, top_n=3)
    again = make(Fake(), tmp_path).rerank("q", DOCS, top_n=3)
    assert first == again
    assert len(fake.calls) == 1


def test_a_changed_document_or_query_is_a_new_request(tmp_path: Path) -> None:
    fake = Fake(ok(0.1, 0.2, 0.3), ok(0.3, 0.2, 0.1))
    r = make(fake, tmp_path)
    r.rerank("q", DOCS, top_n=3)
    r.rerank("q", [*DOCS[:2], ("d3", "different")], top_n=3)
    assert len(fake.calls) == 2


def test_the_key_is_a_bearer_header_and_never_in_the_url_or_body(tmp_path: Path) -> None:
    fake = Fake(ok(0.1, 0.2, 0.3))
    make(fake, tmp_path).rerank("q", DOCS, top_n=3)
    url, headers, body = fake.calls[0]
    assert headers["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in url
    assert "secret-key" not in str(body)
    assert body["model"] == "rerank-v4.0-pro"
    assert body["documents"] == ["alpha text", "beta text", "gamma text"]


def test_a_rate_limit_is_waited_out_and_retried(tmp_path: Path) -> None:
    sleeps: list[float] = []
    fake = Fake((429, {}), ok(0.1, 0.9, 0.5))
    got = make(fake, tmp_path, sleeps).rerank("q", DOCS, top_n=3)
    assert got[0][0] == "d2"
    assert any(s >= 10 for s in sleeps)


def test_repeated_failure_raises_without_echoing_the_key(tmp_path: Path) -> None:
    fake = Fake(*[(500, {"message": "boom"})] * 5)
    with pytest.raises(RerankError) as err:
        make(fake, tmp_path).rerank("q", DOCS, top_n=3)
    assert "secret-key" not in str(err.value)
    assert "500" in str(err.value)


def test_a_malformed_answer_is_an_error_not_a_silent_empty_ranking(tmp_path: Path) -> None:
    with pytest.raises(RerankError):
        make(Fake((200, {"unexpected": True})), tmp_path).rerank("q", DOCS, top_n=3)


def test_calls_are_paced_to_the_trial_limit(tmp_path: Path) -> None:
    sleeps: list[float] = []
    fake = Fake(ok(0.1, 0.2, 0.3), ok(0.3, 0.2, 0.1))
    r = make(fake, tmp_path, sleeps)
    r.rerank("a", DOCS, top_n=3)
    r.rerank("b", DOCS, top_n=3)
    assert any(s > 0 for s in sleeps)


def test_the_real_transport_refuses_other_origins() -> None:
    with pytest.raises(RerankError, match="origin"):
        cohere_post("file:///etc/passwd", {}, b"{}")


def test_too_many_documents_are_refused_before_any_request(tmp_path: Path) -> None:
    fake = Fake()
    with pytest.raises(ValueError, match="documents"):
        make(fake, tmp_path).rerank("q", [(f"d{i}", "t") for i in range(1_001)], top_n=5)
    assert fake.calls == []
