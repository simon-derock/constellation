import pytest
from hypothesis import given
from hypothesis import strategies as st

from constellation.brain.ownership import (
    GENESIS,
    Claim,
    Departure,
    OwnershipFact,
    RegistryEntry,
    owner_as_of,
    ownership_timeline,
)
from constellation.domain.interval import holder_at

TITAN = RegistryEntry("Project Titan", primary_owner="Sam", former_owners=("Bill", "Sharon"), snapshot_day=59)
DEPARTURES = (Departure("Bill", -579, "EVT-bill"), Departure("Sharon", -306, "EVT-sharon"))
CLAIMS = (Claim("Project Titan", "Sam", 2, "EVT-claim-sam"),)


def timeline(entry: RegistryEntry = TITAN, claims: tuple[Claim, ...] = CLAIMS) -> list[OwnershipFact]:
    return ownership_timeline([entry], claims, DEPARTURES)


def test_former_owners_succeed_each_other_until_their_departures() -> None:
    facts = timeline()
    assert owner_as_of(facts, "Project Titan", -600).owner == "Bill"
    assert owner_as_of(facts, "Project Titan", -579).owner == "Sharon"
    assert owner_as_of(facts, "Project Titan", -307).owner == "Sharon"


def test_a_domain_is_orphaned_between_a_departure_and_the_next_claim() -> None:
    assert owner_as_of(timeline(), "Project Titan", 0).owner is None


def test_a_claim_opens_ownership_on_its_day_with_evidence() -> None:
    fact = owner_as_of(timeline(), "Project Titan", 2)
    assert (fact.owner, fact.origin, fact.evidence, fact.start_known) == ("Sam", "claim", "EVT-claim-sam", True)


def test_a_registry_only_owner_starts_at_the_snapshot_and_says_the_start_is_unknown() -> None:
    titandb = RegistryEntry("TitanDB", primary_owner="Janice", former_owners=("Bill",), snapshot_day=59)
    facts = ownership_timeline([titandb], (), DEPARTURES)
    assert owner_as_of(facts, "TitanDB", 58).owner is None
    fact = owner_as_of(facts, "TitanDB", 59)
    assert (fact.owner, fact.origin, fact.start_known) == ("Janice", "registry_snapshot", False)


def test_a_claim_that_disagrees_with_the_registry_is_kept_and_the_snapshot_supersedes_it() -> None:
    entry = RegistryEntry("redis-cache", primary_owner="Yusuf", former_owners=(), snapshot_day=59)
    facts = ownership_timeline([entry], (Claim("redis-cache", "Liam", 14, "EVT-liam"),), ())
    assert owner_as_of(facts, "redis-cache", 20).owner == "Liam"
    assert owner_as_of(facts, "redis-cache", 59).owner == "Yusuf"


def test_unknown_domains_are_refused() -> None:
    with pytest.raises(KeyError):
        owner_as_of(timeline(), "nope", 0)


@given(st.integers(min_value=GENESIS, max_value=200))
def test_every_domain_has_at_most_one_owner_on_every_day(day: int) -> None:
    facts = timeline()
    holder_at([(f.owner, f.interval) for f in facts if f.domain == "Project Titan"], day)
