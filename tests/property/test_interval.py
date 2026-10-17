import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from constellation.domain.interval import Interval, holder_at

ticks = st.integers(min_value=-1_000, max_value=1_000)


@st.composite
def intervals(draw: st.DrawFn) -> Interval:
    start = draw(ticks)
    length = draw(st.none() | st.integers(min_value=1, max_value=500))
    return Interval(start, None if length is None else start + length)


@given(intervals(), ticks)
def test_contains_is_half_open(iv: Interval, t: int) -> None:
    assert iv.contains(t) == (iv.start <= t and (iv.end is None or t < iv.end))


@given(ticks, st.integers(1, 50), st.integers(1, 50))
def test_handover_tick_belongs_to_the_new_holder(start: int, a: int, b: int) -> None:
    old, new = Interval(start, start + a), Interval(start + a, start + a + b)
    assert not old.contains(start + a)
    assert new.contains(start + a)


@given(intervals(), intervals())
def test_overlap_is_symmetric_and_means_a_shared_tick(x: Interval, y: Interval) -> None:
    shared = any(x.contains(t) and y.contains(t) for t in range(-1_000, 2_001))
    assert x.overlaps(y) == y.overlaps(x) == shared


@given(ticks, st.integers(1, 100))
def test_close_at_ends_an_open_interval_exactly_there(start: int, d: int) -> None:
    closed = Interval(start).close_at(start + d)
    assert closed == Interval(start, start + d)
    assert closed.contains(start + d - 1)
    assert not closed.contains(start + d)


def test_empty_and_reversed_intervals_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        Interval(5, 5)
    with pytest.raises(ValueError, match="empty"):
        Interval(5, 4)


def test_closing_twice_or_before_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="already closed"):
        Interval(0, 3).close_at(2)
    with pytest.raises(ValueError, match="after start"):
        Interval(3).close_at(3)


@given(ticks, st.lists(st.integers(1, 30), min_size=1, max_size=8), st.integers(0, 400))
def test_a_handover_chain_has_exactly_one_holder_at_each_tick(
    start: int, spans: list[int], probe: int
) -> None:
    bounds = [start]
    for span in spans:
        bounds.append(bounds[-1] + span)
    chain = [(f"owner{i}", Interval(lo, hi)) for i, (lo, hi) in enumerate(itertools.pairwise(bounds))]
    t = start + probe
    expected = next((who for who, iv in chain if iv.contains(t)), None)
    assert holder_at(chain, t) == expected


def test_overlapping_holders_are_a_data_defect_not_a_choice() -> None:
    with pytest.raises(ValueError, match="2 holders"):
        holder_at([("a", Interval(0, 10)), ("b", Interval(5))], 7)
