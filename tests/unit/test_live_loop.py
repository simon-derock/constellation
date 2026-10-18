import threading
from collections.abc import Callable, Mapping

from constellation.live.loop import next_delay, run_forever, start
from constellation.live.sync import SyncReport

OK = SyncReport(2, 5, 1, False, None)


def limited(reset: int) -> SyncReport:
    return SyncReport(1, 1, 0, True, reset)


def test_a_clean_sync_waits_the_normal_interval() -> None:
    assert next_delay(OK, every=300, now=1_000) == 300


def test_a_rate_limit_waits_until_the_reset_but_never_less_than_the_interval() -> None:
    assert next_delay(limited(1_900), every=300, now=1_000) == 900
    assert next_delay(limited(1_050), every=300, now=1_000) == 300


def test_a_far_reset_is_capped_so_the_loop_keeps_checking() -> None:
    assert next_delay(limited(1_000_000), every=300, now=1_000) == 3_600


def drive(results: list[SyncReport | Exception], every: int = 300) -> list[float]:
    stop = threading.Event()
    delays: list[float] = []
    queue = list(results)

    def sync() -> SyncReport:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def wait(seconds: float) -> bool:
        delays.append(seconds)
        if not queue:
            stop.set()
        return stop.is_set()

    run_forever(sync, stop, every, now=lambda: 1_000, wait=wait)
    return delays


def test_the_loop_survives_a_failed_cycle_and_tries_again() -> None:
    assert drive([OK, RuntimeError("network down"), OK]) == [300, 300, 300]


def test_the_loop_stops_when_asked_without_another_sync() -> None:
    stop = threading.Event()
    stop.set()
    calls: list[int] = []

    def sync() -> SyncReport:
        calls.append(1)
        return OK

    run_forever(sync, stop, 300)
    assert calls == []


def test_without_credentials_no_thread_is_started() -> None:
    def never(_: Mapping[str, str]) -> Callable[[], SyncReport]:
        raise AssertionError("must not build a syncer without credentials")

    assert start({}, never) is None
    assert start({"GITHUB_TOKEN": "t"}, never) is None
