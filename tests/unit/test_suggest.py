from constellation.actions.suggest import Suggestion, ownership_gaps, suggestions_from_rows


def span(owner: str, start: int, end: int | None, origin: str, known: bool, evidence: str = "e") -> dict[str, object]:
    return {"owner": owner, "from": start, "to": end, "origin": origin, "start_known": known, "evidence": evidence}


INTERVALS = {
    "kubernetes-deploy": [
        span("Morgan", -1000, 34, "former_owner", False, "EVT-dep"),
        span("Sanjay", 42, None, "claim", True, "EVT-claim"),
    ],
    "Project Titan": [
        span("Sharon", -579, -306, "former_owner", False),
        span("Sam", 2, None, "claim", True, "EVT-sam"),
    ],
    "TitanDB": [
        span("Bill", -1000, -579, "former_owner", False),
        span("Janice", 59, None, "registry_snapshot", False, "registry"),
    ],
    "redis-cache": [span("Yusuf", 14, None, "claim", True, "EVT-y")],
}


def test_a_recorded_gap_between_a_departure_and_a_claim_is_reported_with_its_days() -> None:
    gaps = {g.domain: g for g in ownership_gaps(INTERVALS)}
    assert (gaps["kubernetes-deploy"].start, gaps["kubernetes-deploy"].end) == (34, 42)
    assert gaps["kubernetes-deploy"].previous_owner == "Morgan"
    assert gaps["kubernetes-deploy"].next_owner == "Sanjay"


def test_a_gap_is_clipped_to_the_era_the_records_cover() -> None:
    gap = next(g for g in ownership_gaps(INTERVALS) if g.domain == "Project Titan")
    assert (gap.start, gap.end) == (0, 2)


def test_a_gap_before_an_owner_with_no_recorded_start_is_not_claimed() -> None:
    # TitanDB's current owner is only known from a final snapshot; the empty span before it is not a measured gap
    assert "TitanDB" not in {g.domain for g in ownership_gaps(INTERVALS)}


def test_a_domain_that_was_never_unowned_has_no_gap() -> None:
    assert "redis-cache" not in {g.domain for g in ownership_gaps(INTERVALS)}


def test_a_suggestion_is_deterministic_and_carries_what_a_reviewer_needs() -> None:
    first = suggestions_from_rows(INTERVALS, "abc123")
    second = suggestions_from_rows(INTERVALS, "abc123")
    assert first == second
    top = next(s for s in first if "kubernetes-deploy" in s.title)
    assert isinstance(top, Suggestion)
    assert top.kind == "file_issue"
    assert "day 34" in top.body
    assert "Morgan" in top.body
    assert "Sanjay" in top.body
    assert "abc123" in top.body
    assert len(top.payload_hash) == 64


def test_changing_the_evidence_changes_the_payload_hash() -> None:
    a = suggestions_from_rows(INTERVALS, "abc123")[0]
    b = suggestions_from_rows(INTERVALS, "def456")[0]
    assert a.payload_hash != b.payload_hash
