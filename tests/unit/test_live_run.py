import pytest

from constellation.live.embed import CohereEmbedder
from constellation.live.run import credentials, embedder_from_env


def test_both_a_token_and_a_long_enough_key_are_required() -> None:
    assert credentials({"GITHUB_TOKEN": "t", "PSEUDONYM_KEY": "k" * 32}) == ("t", "k" * 32)
    with pytest.raises(SystemExit, match="GITHUB_TOKEN"):
        credentials({"PSEUDONYM_KEY": "k" * 32})
    with pytest.raises(SystemExit, match="PSEUDONYM_KEY"):
        credentials({"GITHUB_TOKEN": "t", "PSEUDONYM_KEY": "short"})


def test_the_error_never_echoes_a_secret() -> None:
    with pytest.raises(SystemExit) as err:
        credentials({"GITHUB_TOKEN": "super-secret", "PSEUDONYM_KEY": "short"})
    assert "super-secret" not in str(err.value)


def test_the_first_cohere_key_that_is_set_builds_the_embedder() -> None:
    assert embedder_from_env({}) is None
    assert embedder_from_env({"COHERE_KEY": ""}) is None
    assert isinstance(embedder_from_env({"COHERENCE_API_KEY": "k"}), CohereEmbedder)
    assert embedder_from_env({"COHERE_KEY": "a", "COHERE_API_KEY": "b"}) is not None


def test_the_embedding_size_is_configurable_and_defaults_to_256() -> None:
    assert embedder_from_env({"COHERE_KEY": "k"}).dim == 256  # type: ignore[union-attr]
    assert embedder_from_env({"COHERE_KEY": "k", "EMBED_DIM": "512"}).dim == 512  # type: ignore[union-attr]
