import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from constellation.domain.ids import entity_id

tenants = st.sampled_from(["apex", "redwood", "falkordb"])
kinds = st.sampled_from(["Person", "Artifact", "Claim", "Component", "Space"])
keys = st.text(min_size=1, max_size=40)


@given(tenants, kinds, keys)
def test_ids_are_deterministic_uuid5(tenant: str, kind: str, key: str) -> None:
    first = entity_id(tenant, kind, key)
    assert first == entity_id(tenant, kind, key)
    assert first.version == 5


@given(kinds, keys)
def test_the_same_natural_key_never_collides_across_tenants(kind: str, key: str) -> None:
    assert entity_id("apex", kind, key) != entity_id("redwood", kind, key)


@given(tenants, keys)
def test_the_same_natural_key_never_collides_across_kinds(tenant: str, key: str) -> None:
    assert entity_id(tenant, "Person", key) != entity_id(tenant, "Artifact", key)


@pytest.mark.parametrize("kind", ["", "person", "Per:son", "Person Node"])
def test_kind_must_be_a_label(kind: str) -> None:
    with pytest.raises(ValueError, match="label"):
        entity_id("apex", kind, "k")


def test_empty_natural_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="natural key"):
        entity_id("apex", "Person", "")


def test_ids_are_stable_across_releases() -> None:
    # pinned: changing the namespace root would orphan every node in every snapshot
    assert entity_id("apex", "Person", "emp-001") == uuid.UUID("1a8748b1-efdc-538e-956c-753ba3553610")
