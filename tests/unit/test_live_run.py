import pytest

from constellation.live.run import credentials


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
