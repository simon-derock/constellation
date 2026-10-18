from pathlib import Path
from typing import Any

import pytest

from constellation.live.embed import CohereEmbedder, EmbedError, cohere_embed_post


class Fake:
    def __init__(self, *replies: tuple[int, dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        import json

        self.calls.append((url, headers, json.loads(body)))
        return self.replies.pop(0)


def vectors(n: int, dim: int = 3) -> tuple[int, dict[str, Any]]:
    return 200, {"embeddings": {"float": [[float(i)] * dim for i in range(n)]}}


def make(fake: Fake, sleeps: list[float] | None = None, tmp: Path | None = None) -> CohereEmbedder:
    record = sleeps.append if sleeps is not None else (lambda _: None)
    return CohereEmbedder("secret-key", dim=3, transport=fake, sleep=record, cache_dir=tmp)


def test_texts_come_back_as_vectors_in_the_order_given() -> None:
    got = make(Fake(vectors(2))).embed(["a", "b"], "document")
    assert got == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]


def test_documents_and_queries_use_different_input_types() -> None:
    fake = Fake(vectors(1), vectors(1))
    e = make(fake)
    e.embed(["x"], "document")
    e.embed(["x"], "query")
    assert [c[2]["input_type"] for c in fake.calls] == ["search_document", "search_query"]
    assert fake.calls[0][2]["output_dimension"] == 3
    assert fake.calls[0][2]["embedding_types"] == ["float"]


def test_more_than_one_batch_is_split_and_rejoined_in_order() -> None:
    fake = Fake(vectors(96), vectors(4))
    got = make(fake).embed([f"t{i}" for i in range(100)], "document")
    assert len(got) == 100
    assert [len(c[2]["texts"]) for c in fake.calls] == [96, 4]


def test_the_key_is_a_bearer_header_and_nowhere_else() -> None:
    fake = Fake(vectors(1))
    make(fake).embed(["x"], "query")
    url, headers, body = fake.calls[0]
    assert headers["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in url
    assert "secret-key" not in str(body)


def test_a_rate_limit_is_waited_out_and_retried() -> None:
    sleeps: list[float] = []
    got = make(Fake((429, {}), vectors(1)), sleeps).embed(["x"], "query")
    assert len(got) == 1
    assert any(s >= 5 for s in sleeps)


def test_repeated_failure_raises_without_echoing_the_key() -> None:
    with pytest.raises(EmbedError) as err:
        make(Fake(*[(500, {"message": "boom"})] * 5)).embed(["x"], "query")
    assert "secret-key" not in str(err.value)
    assert "500" in str(err.value)


def test_a_wrong_number_or_width_of_vectors_is_an_error_not_silent_corruption() -> None:
    with pytest.raises(EmbedError, match="vectors"):
        make(Fake(vectors(1))).embed(["a", "b"], "document")
    with pytest.raises(EmbedError, match="dimension"):
        make(Fake((200, {"embeddings": {"float": [[1.0, 2.0]]}}))).embed(["a"], "document")


def test_empty_input_makes_no_request() -> None:
    fake = Fake()
    assert make(fake).embed([], "document") == []
    assert fake.calls == []


def test_an_identical_text_is_embedded_once_and_then_remembered(tmp_path: Path) -> None:
    fake = Fake(vectors(1))
    first = make(fake, tmp=tmp_path).embed(["same text"], "query")
    again = make(Fake(), tmp=tmp_path).embed(["same text"], "query")
    assert first == again
    assert len(fake.calls) == 1


def test_the_real_transport_refuses_other_origins() -> None:
    with pytest.raises(EmbedError, match="origin"):
        cohere_embed_post("file:///etc/passwd", {}, b"{}")
