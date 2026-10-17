import pytest

from constellation.brain.access import SimEvent, jira_project_visible, subsystem_access, visible_artifacts

ROLES = {"Jax": "engineering_backend", "Priya": "design", "Nora": "external"}


def ev(day: int, type_: str, actors: list[str], ids: dict[str, str]) -> SimEvent:
    return SimEvent(day=day, type=type_, actors=tuple(actors), artifact_ids=tuple(ids.items()))


def cone(events: list[SimEvent], actor: str, day: int) -> frozenset[str]:
    return visible_artifacts(events, actor, ROLES.get(actor, "external"), as_of_day=day)


def test_direct_involvement_inside_role_access_is_visible() -> None:
    events = [ev(2, "design_discussion", ["Jax"], {"jira": "ENG-1", "slack_thread": "s-1"})]
    assert cone(events, "Jax", 2) == {"ENG-1", "s-1"}


def test_role_gate_drops_subsystems_the_role_cannot_open() -> None:
    # design has no jira access, so direct involvement is not enough
    events = [ev(2, "design_discussion", ["Priya"], {"jira": "ENG-1", "slack": "s-2"})]
    assert cone(events, "Priya", 2) == {"s-2"}


def test_broadcast_reaches_uninvolved_actors_with_channel_access() -> None:
    events = [ev(3, "incident_opened", ["Jax"], {"slack": "inc-1", "jira": "ENG-9"})]
    assert cone(events, "Priya", 3) == {"inc-1"}


def test_non_broadcast_events_stay_with_their_actors() -> None:
    events = [ev(3, "watercooler_chat", ["Jax"], {"slack": "w-1"})]
    assert cone(events, "Priya", 3) == frozenset()


def test_the_horizon_is_inclusive_of_its_own_day() -> None:
    events = [ev(5, "standup", ["Jax"], {"slack": "su-5"})]
    assert cone(events, "Jax", 4) == frozenset()
    assert cone(events, "Jax", 5) == {"su-5"}


def test_history_before_day_one_never_enters_a_cone() -> None:
    # faithful to OrgForge: cones accumulate from business day 1
    assert cone([ev(0, "standup", ["Jax"], {"slack": "g-0"})], "Jax", 10) == frozenset()


def test_unmapped_artifact_keys_never_enter_a_cone() -> None:
    # faithful to OrgForge: zoom_transcript is not in the subsystem map
    events = [ev(2, "design_discussion", ["Jax"], {"zoom_transcript": "z-1", "eml_path": "x.eml"})]
    assert cone(events, "Jax", 2) == frozenset()


def test_external_actors_see_nothing() -> None:
    assert (
        cone([ev(2, "inbound_external_email", ["Nora", "Jax"], {"email": "e-1"})], "Nora", 2) == frozenset()
    )


@pytest.mark.parametrize(
    ("ticket", "role", "visible"),
    [
        ("ENG-1", "engineering_mobile", True),
        ("ENG-1", "design", False),
        ("HR-3", "hr_ops", True),
        ("ORG-100", "qa_support", True),
        ("XYZ-1", "design", True),
    ],
)
def test_jira_project_gate(ticket: str, role: str, visible: bool) -> None:
    assert jira_project_visible(ticket, role) is visible


def test_role_access_matches_the_harness_table() -> None:
    assert subsystem_access("design") == {"slack", "confluence", "zoom", "email"}
    assert subsystem_access("unknown-role") == frozenset()
