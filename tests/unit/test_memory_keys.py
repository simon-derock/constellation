import pytest

from constellation.memory.ask import Asked, grounded, seal, verdict_of


def key(question: str, kind: str = "SILENCE", actor: str = "", day: int = 0, tenant: str = "apex") -> str:
    return Asked.of(tenant, kind, question, actor, day).key


def test_case_punctuation_and_spacing_do_not_make_a_different_question() -> None:
    assert key("Was a risk flag raised?") == key("  was a RISK flag   raised ")
    assert key("Was a risk flag raised?") != key("Was a risk flag closed?")


def test_a_perspective_is_the_same_question_only_for_the_same_person_and_day() -> None:
    ask = "Would Alex have known?"
    assert key(ask, "PERSPECTIVE", "Alex", 28) == key(ask.lower(), "PERSPECTIVE", "Alex", 28)
    assert key(ask, "PERSPECTIVE", "Alex", 28) != key(ask, "PERSPECTIVE", "Tom", 28)
    assert key(ask, "PERSPECTIVE", "Alex", 28) != key(ask, "PERSPECTIVE", "Alex", 29)


def test_who_asks_and_when_do_not_split_the_other_kinds() -> None:
    assert key("Why?", "COUNTERFACTUAL", "Alex", 3) == key("Why?", "COUNTERFACTUAL", "", 0)


def test_kind_and_tenant_are_part_of_the_question() -> None:
    assert key("Same words") != key("Same words", "COUNTERFACTUAL")
    assert key("Same words") != key("Same words", tenant="other")


def test_the_seal_matches_the_one_the_web_draws() -> None:
    # computed by web/src/lib/bits.ts sealHash for two 64-character hashes, so a turn names the seal on screen
    assert seal(["a" * 64, "b" * 64]) == "f5053087cc20dde6895134512d42e7e8a6dd52fdcee347e3474c7bcfab64d0b7"
    assert seal(["ab", "c"]) != seal(["a", "bc"])


@pytest.mark.parametrize(
    ("kind", "results", "expected"),
    [
        ("SILENCE", [("absence", {}, {"known_expectation": True})], True),
        ("SILENCE", [("absence", {}, {"known_expectation": False})], False),
        ("SILENCE", [("find_events", {}, [])], False),
        ("PERSPECTIVE", [("could_have_known", {}, {"could_actor_have_known": False})], True),
        ("COUNTERFACTUAL", [("counterfactual", {}, {"linked": True})], True),
        ("COUNTERFACTUAL", [("counterfactual", {}, {"linked": False})], False),
        ("COUNTERFACTUAL", [("absence", {}, {"known_expectation": True})], False),
        ("SILENCE", [], False),
    ],
)
def test_an_answer_is_grounded_only_when_the_decisive_tool_decided_it(
    kind: str, results: list[tuple[str, dict[str, object], object]], expected: bool
) -> None:
    assert grounded(kind, results) is expected


def test_only_a_real_boolean_is_a_verdict() -> None:
    assert verdict_of("SILENCE", {"exists": False}) is False
    assert verdict_of("SILENCE", {"exists": "false"}) is None
    assert verdict_of("SILENCE", {}) is None
    assert verdict_of("PERSPECTIVE", {"exists": True}) is None
