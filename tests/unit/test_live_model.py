from typing import Any

from constellation.live.model import Claim, Item, facts_of, item_from_github, plan_changes

KEY = "k" * 32
T0, T1, T2 = 1_760_000_000, 1_760_100_000, 1_760_200_000


def raw(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "number": 7,
        "title": "fix(runtime): handle negative ID range bounds",
        "state": "open",
        "user": {"login": "gkorland", "type": "User"},
        "assignees": [],
        "labels": [{"name": "lgtm"}],
        "created_at": "2025-10-09T08:00:00Z",
        "updated_at": "2025-10-09T08:00:00Z",
        "closed_at": None,
    }
    return {**base, **over}


def item(**over: Any) -> Item:
    parsed = item_from_github("FalkorDB", raw(**over), KEY)
    assert parsed is not None
    return parsed


def test_an_item_carries_aliases_and_never_a_login_or_a_body() -> None:
    parsed = item(body="mail me at someone@example.com", assignees=[{"login": "swilly22", "type": "User"}])
    dumped = repr(parsed)
    assert "gkorland" not in dumped
    assert "swilly22" not in dumped
    assert "someone@example.com" not in dumped
    assert parsed.author is not None
    assert len(parsed.assignees) == 1


def test_bot_authored_items_are_dropped_and_bot_assignees_are_ignored() -> None:
    assert item_from_github("r", raw(user={"login": "dependabot[bot]", "type": "Bot"}), KEY) is None
    parsed = item(assignees=[{"login": "dependabot[bot]", "type": "Bot"}])
    assert parsed.assignees == ()


def test_state_distinguishes_open_closed_and_merged() -> None:
    assert item().state == "open"
    assert item(state="closed", closed_at="2025-10-10T00:00:00Z").state == "closed"
    merged = item(state="closed", closed_at="2025-10-10T00:00:00Z", pull_request={"merged_at": "2025-10-10T00:00:00Z"})
    assert (merged.kind, merged.state) == ("pr", "merged")
    assert item().kind == "issue"


def test_titles_are_bounded_and_stripped_of_control_characters() -> None:
    assert len(item(title="t" * 500).title) <= 200
    assert item(title="a\x00b\x07c").title == "abc"


def test_first_sight_of_an_open_item_records_one_open_claim_from_its_creation() -> None:
    plan = plan_changes({}, [item()], observed_at=T2)
    states = [c for c in plan.new_claims if c.predicate == "state"]
    assert [(c.value, c.valid_from, c.valid_to) for c in states] == [("open", item().created_at, None)]
    assert plan.changes == []


def test_first_sight_of_a_closed_item_reconstructs_its_history_without_calling_it_a_change() -> None:
    closed = item(state="closed", closed_at="2025-10-10T00:00:00Z")
    plan = plan_changes({}, [closed], observed_at=T2)
    states = sorted((c.value, c.valid_from, c.valid_to) for c in plan.new_claims if c.predicate == "state")
    assert states == [("closed", closed.closed_at, None), ("open", closed.created_at, closed.closed_at)]
    assert plan.changes == []
    assert all(c.origin == "derived" for c in plan.new_claims if c.predicate == "state")


def test_a_later_transition_closes_the_old_claim_links_the_new_one_and_reports_the_change() -> None:
    first = plan_changes({}, [item()], observed_at=T1)
    open_claims = {(c.item, c.predicate): c for c in first.new_claims if c.valid_to is None}
    closed = item(state="closed", closed_at="2025-10-10T00:00:00Z")
    plan = plan_changes(open_claims, [closed], observed_at=T2)
    old = open_claims[(closed.doc_id, "state")]
    assert (old.kid, closed.closed_at) in {(kid, at) for kid, at in plan.closures}
    new = next(c for c in plan.new_claims if c.predicate == "state")
    assert (new.value, new.valid_from, new.supersedes) == ("closed", closed.closed_at, old.kid)
    assert [(c.predicate, c.old, c.new) for c in plan.changes] == [("state", "open", "closed")]


def test_observing_the_same_thing_twice_changes_nothing() -> None:
    first = plan_changes({}, [item()], observed_at=T1)
    open_claims = {(c.item, c.predicate): c for c in first.new_claims if c.valid_to is None}
    again = plan_changes(open_claims, [item()], observed_at=T2)
    assert (again.new_claims, again.closures, again.changes) == ([], [], [])


def test_a_reopened_item_is_dated_by_when_it_was_seen_because_the_api_gives_no_reopen_time() -> None:
    closed = item(state="closed", closed_at="2025-10-10T00:00:00Z")
    start = plan_changes({}, [closed], observed_at=T1)
    open_claims = {(c.item, c.predicate): c for c in start.new_claims if c.valid_to is None}
    plan = plan_changes(open_claims, [item()], observed_at=T2)
    assert [(c.old, c.new) for c in plan.changes if c.predicate == "state"] == [("closed", "open")]
    reopened = next(c for c in plan.new_claims if c.predicate == "state")
    assert (reopened.valid_from, reopened.origin) == (T2, "observed")


def test_a_new_assignee_supersedes_the_old_assignment() -> None:
    first = plan_changes({}, [item(assignees=[{"login": "a", "type": "User"}])], observed_at=T1)
    open_claims = {(c.item, c.predicate): c for c in first.new_claims if c.valid_to is None}
    plan = plan_changes(open_claims, [item(assignees=[{"login": "b", "type": "User"}])], observed_at=T2)
    assert [c.predicate for c in plan.changes] == ["assignees"]
    assert plan.closures


def test_claim_ids_are_deterministic_so_a_replayed_sync_cannot_duplicate_them() -> None:
    a = plan_changes({}, [item()], observed_at=T1).new_claims
    b = plan_changes({}, [item()], observed_at=T2).new_claims
    assert [c.kid for c in a] == [c.kid for c in b]
    assert isinstance(a[0], Claim)


def test_facts_cover_state_assignees_and_labels() -> None:
    assert {f.predicate for f in facts_of(item(), observed_at=T1)} == {"state", "assignees", "labels"}
