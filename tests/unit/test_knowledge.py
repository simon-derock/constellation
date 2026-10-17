from constellation.brain.access import SimEvent, born_days, could_have_known

type Corpus = frozenset[str]

ROLE = {"Jax": "engineering_backend", "Tom": "hr_ops", "Priya": "design"}


def ev(eid: str, day: int, kind: str, actors: list[str], ids: dict[str, str], spawned: bool = False) -> SimEvent:
    return SimEvent(day, kind, tuple(actors), tuple(ids.items()), event_id=eid, spawned_doc=spawned)


def known(events: list[SimEvent], actor: str, target: SimEvent, day: int, corpus: frozenset[str] = frozenset()) -> bool:
    return could_have_known(events, born_days(events), actor, ROLE[actor], target, day, corpus)


def test_a_private_chat_is_unknowable_to_outsiders() -> None:
    chat = ev("e1", 39, "watercooler_chat", ["Jax"], {"slack_thread": "dm-1", "slack_path": "dm-1.json"})
    assert not known([chat], "Tom", chat, 39)


def test_a_broadcast_incident_is_knowable_on_its_day() -> None:
    inc = ev("e2", 8, "incident_opened", ["Jax"], {"slack": "inc-8"})
    assert known([inc], "Tom", inc, 8)


def test_an_artifact_not_yet_produced_cannot_be_missed() -> None:
    # missed artifacts only count once they exist on the simulation clock
    later = ev("e3", 12, "retrospective", ["Jax"], {"confluence": "RETRO-1"})
    assert known([later], "Tom", later, 11)


def test_knowledge_propagates_through_a_shared_earlier_event() -> None:
    private = ev("e4", 5, "design_discussion", ["Jax"], {"slack_thread": "t-5", "jira": "ENG-5"})
    shared = ev("e5", 4, "async_question", ["Priya", "Jax"], {"slack_thread": "t-5"})
    assert known([shared, private], "Priya", private, 5)


def test_a_design_discussion_that_spawned_a_page_is_discoverable_with_confluence_access() -> None:
    dd = ev("e6", 6, "design_discussion", ["Jax"], {"confluence": "CONF-9", "slack_thread": "t-6"}, spawned=True)
    assert known([dd], "Tom", dd, 6, corpus=frozenset({"CONF-9"}))
    assert not known([dd], "Tom", dd, 6, corpus=frozenset())


def test_born_day_is_the_earliest_producing_event() -> None:
    a = ev("a", 7, "standup", ["Jax"], {"slack": "s"})
    b = ev("b", 3, "standup", ["Jax"], {"slack": "s", "eml_path": "x.eml"})
    assert born_days([a, b]) == {"s": 3}
