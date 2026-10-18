import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

type Transport = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, Any]]]

_ORIGIN = "https://api.cohere.com/"
_MAX_DOCUMENTS = 1_000
_DOC_CHARS = 12_000
_ATTEMPTS = 5
# the free trial key allows ten rerank calls a minute: pace to it instead of discovering it through 429s
_MIN_INTERVAL = 6.5


class RerankError(Exception):
    pass


def cohere_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    # only the provider's https origin is ever opened, so file:// and other schemes cannot be
    if not url.startswith(_ORIGIN):
        raise RerankError("refusing to open a URL outside the provider origin")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310  # nosec B310
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}


class CohereReranker:
    # reorders candidate documents by a cross-encoder; every answer is cached on disk by the exact request, so a
    # re-run, a metric change or a crash costs no further calls against a quota that is small and shared
    def __init__(
        self,
        key: str,
        model: str = "rerank-v4.0-pro",
        transport: Transport = cohere_post,
        cache_dir: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key, self.model, self._transport = key, model, transport
        self._cache, self._sleep, self._clock = cache_dir, sleep, clock
        self._last = -_MIN_INTERVAL
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query: str, docs: Sequence[tuple[str, str]], top_n: int) -> Path | None:
        if self._cache is None:
            return None
        seed = json.dumps([self.model, query, top_n, [[i, t[:_DOC_CHARS]] for i, t in docs]], ensure_ascii=False)
        return self._cache / f"{hashlib.sha256(seed.encode()).hexdigest()}.json"

    def _post(self, query: str, texts: list[str], top_n: int) -> list[dict[str, Any]]:
        body = json.dumps({"model": self.model, "query": query, "documents": texts, "top_n": top_n}).encode()
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        status = 0
        for attempt in range(_ATTEMPTS):
            wait = _MIN_INTERVAL - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            status, payload = self._transport(f"{_ORIGIN}v2/rerank", headers, body)
            if status == 200:
                results = payload.get("results")
                if not isinstance(results, list):
                    raise RerankError("the reranker answered without results")
                return results
            if status not in (429, 500, 502, 503, 504):
                break
            self._sleep(15.0 * (attempt + 1) if status == 429 else 2.0**attempt)
        # the provider's message describes the request; the key is never part of it
        raise RerankError(f"reranking failed with HTTP {status}")

    def rerank(self, query: str, docs: Sequence[tuple[str, str]], top_n: int) -> list[tuple[str, float]]:
        if len(docs) > _MAX_DOCUMENTS:
            raise ValueError(f"too many documents for one request (limit {_MAX_DOCUMENTS})")
        path = self._path(query, docs, top_n)
        if path is not None and path.exists():
            return [(str(i), float(s)) for i, s in json.loads(path.read_text())]
        results = self._post(query, [t[:_DOC_CHARS] for _, t in docs], top_n)
        # ties keep the input order: the ranking is a function of the request alone
        ranked = sorted(((int(r["index"]), float(r["relevance_score"])) for r in results), key=lambda p: (-p[1], p[0]))
        out = [(docs[i][0], score) for i, score in ranked][:top_n]
        if path is not None:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out))
            tmp.replace(path)
        return out
