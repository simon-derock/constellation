import logging
import threading
import time
from collections.abc import Callable, Mapping

from constellation.live.sync import SyncReport

_log = logging.getLogger("constellation.live")
_MAX_WAIT = 3_600
_MIN_KEY = 16

type Builder = Callable[[Mapping[str, str]], Callable[[], SyncReport]]


def next_delay(report: SyncReport, every: int, now: int) -> int:
    # a rate limit is waited out until its reset, but never longer than an hour: the loop keeps checking
    if report.rate_limited and report.retry_at is not None:
        return min(max(report.retry_at - now, every), _MAX_WAIT)
    return every


def run_forever(
    sync: Callable[[], SyncReport],
    stop: threading.Event,
    every: int,
    now: Callable[[], int] = lambda: int(time.time()),
    wait: Callable[[float], bool] | None = None,
) -> None:
    pause = wait or stop.wait
    while not stop.is_set():
        delay = every
        try:
            report = sync()
            delay = next_delay(report, every, now())
            _log.info("live sync: %s", report)
        except Exception:
            # a failed cycle must not end the loop: the next one starts from the saved cursors
            _log.exception("live sync failed")
        if pause(delay):
            return


def start(
    env: Mapping[str, str], build: Callable[[Mapping[str, str]], Callable[[], SyncReport]]
) -> threading.Thread | None:
    # the sync needs both a token and a key; without them the live tenant simply serves what it was shipped with
    if not env.get("GITHUB_TOKEN") or len(env.get("PSEUDONYM_KEY", "")) < _MIN_KEY:
        return None
    sync = build(env)
    every = int(env.get("LIVE_SYNC_SECONDS", "600"))
    thread = threading.Thread(target=run_forever, args=(sync, threading.Event(), every), name="live-sync", daemon=True)
    thread.start()
    return thread
