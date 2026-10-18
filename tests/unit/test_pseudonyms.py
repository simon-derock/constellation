import re

import pytest

from constellation.live.pseudonyms import ADJECTIVES, NOUNS, is_bot, pseudonym

KEY = "k" * 32
ALIAS = re.compile(r"^[a-z]+-[a-z]+-[0-9a-f]{2}$")


def test_an_alias_is_stable_for_one_person_and_one_key() -> None:
    assert pseudonym("gkorland", KEY) == pseudonym("gkorland", KEY)
    assert ALIAS.fullmatch(pseudonym("gkorland", KEY))


def test_logins_differing_only_in_case_are_the_same_person() -> None:
    assert pseudonym("GKorland", KEY) == pseudonym("gkorland", KEY)


def test_a_different_key_gives_different_aliases_so_they_cannot_be_reversed_by_guessing() -> None:
    assert pseudonym("gkorland", KEY) != pseudonym("gkorland", "z" * 32)


def test_an_alias_never_contains_any_part_of_the_login() -> None:
    for login in ["gkorland", "swilly22", "AviAvni", "barakb", "dudizimber"]:
        alias = pseudonym(login, KEY)
        assert login.lower() not in alias
        assert not any(login.lower()[i : i + 4] in alias for i in range(len(login) - 3))


def test_many_people_rarely_collide() -> None:
    aliases = {pseudonym(f"user{i}", KEY) for i in range(2_000)}
    assert len(aliases) > 1_950


@pytest.mark.parametrize("key", ["", "short", "x" * 15])
def test_a_missing_or_weak_key_is_refused_rather_than_silently_accepted(key: str) -> None:
    with pytest.raises(ValueError, match="key"):
        pseudonym("someone", key)


@pytest.mark.parametrize(
    "user",
    [
        {"login": "dependabot[bot]", "type": "Bot"},
        {"login": "github-actions[bot]", "type": "Bot"},
        {"login": "renovate", "type": "User"},
        {"login": "coderabbitai", "type": "User"},
        {"login": "some-app[bot]", "type": "User"},
        {"login": "ghost", "type": "User"},
        None,
    ],
)
def test_bots_and_deleted_accounts_are_not_people(user: dict[str, str] | None) -> None:
    assert is_bot(user) is True


def test_a_person_is_not_a_bot() -> None:
    assert is_bot({"login": "gkorland", "type": "User"}) is False


def test_the_word_lists_are_large_distinct_and_lowercase() -> None:
    for words in (ADJECTIVES, NOUNS):
        assert len(words) >= 60
        assert len(set(words)) == len(words)
        assert all(word.isalpha() and word == word.lower() for word in words)
