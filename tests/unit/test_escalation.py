import pytest

from constellation.brain.escalation import Chain, chain_from_facts, path_as_of

CHAINS = [
    Chain(("Yusuf", "Sarah"), 13, "EVT-13"),
    Chain(("Yusuf", "Jax"), 21, "EVT-21"),
    Chain(("Yusuf", "Priya"), 29, "EVT-29"),
    Chain(("Deepa", "Jax"), 17, "EVT-17"),
]


@pytest.mark.parametrize(
    ("day", "expected"),
    [(12, None), (13, ("Yusuf", "Sarah")), (20, ("Yusuf", "Sarah")), (21, ("Yusuf", "Jax")), (60, ("Yusuf", "Priya"))],
)
def test_the_latest_observed_chain_on_or_before_the_day_wins(day: int, expected: tuple[str, ...] | None) -> None:
    found = path_as_of(CHAINS, "Yusuf", day)
    assert (found.path if found else None) == expected


def test_paths_belong_to_the_person_who_escalates() -> None:
    found = path_as_of(CHAINS, "Deepa", 30)
    assert found is not None
    assert (found.path, found.evidence) == (("Deepa", "Jax"), "EVT-17")
    assert path_as_of(CHAINS, "Priya", 60) is None


def test_structured_chains_are_read_in_order() -> None:
    facts = {"chain_detail": [["Sanjay", "Engineer"], ["Jax", "Lead"], ["Sarah", "Product Lead"]]}
    assert chain_from_facts(facts, 3, "EVT-3") == Chain(("Sanjay", "Jax", "Sarah"), 3, "EVT-3")


def test_reroutes_are_read_from_their_path_note() -> None:
    note = "[Post-departure re-route after Jordan left] Path: Chloe (Engineering_Mobile Lead) -> Sarah (Product Lead)"
    note += " -- 1 hop(s) to reach leadership."
    assert chain_from_facts({"new_path_note": note}, 12, "EVT-12") == Chain(("Chloe", "Sarah"), 12, "EVT-12")


@pytest.mark.parametrize("facts", [{}, {"chain_detail": [["Solo", "Lead"]]}, {"new_path_note": "no path here"}])
def test_facts_without_a_path_of_two_people_yield_nothing(facts: dict[str, object]) -> None:
    assert chain_from_facts(facts, 1, "EVT-x") is None
