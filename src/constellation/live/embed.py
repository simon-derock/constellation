import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

type Transport = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, Any]]]
type Kind = Literal["document", "query"]

_ORIGIN = "https://api.cohere.com/"
_BATCH = 96
_ATTEMPTS = 5
_INPUT_TYPE = {"document": "search_document", "query": "search_query"}


class EmbedError(Exception):
    pass


class Embedder(Protocol):
    def embed(self, texts: Sequence[str], kind: Kind) -> list[list[float]]: ...


def cohere_embed_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    # only the provider's https origin is ever opened, so file:// and other schemes cannot be
    if not url.startswith(_ORIGIN):
        raise EmbedError("refusing to open a URL outside the provider origin")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  # nosec B310
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}


class CohereEmbedder:
    # turns text into vectors for the graph's HNSW index; an optional disk cache keeps a repeated text from costing a
    # second call against a small shared quota
    def __init__(
        self,
        key: str,
        model: str = "embed-v4.0",
        dim: int = 256,
        transport: Transport = cohere_embed_post,
        sleep: Callable[[float], None] = time.sleep,
        cache_dir: Path | None = None,
    ) -> None:
        self._key, self.model, self.dim, self._transport, self._sleep = key, model, dim, transport, sleep
        self._cache = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, text: str, kind: Kind) -> Path | None:
        if self._cache is None:
            return None
        seed = json.dumps([self.model, self.dim, kind, text], ensure_ascii=False)
        return self._cache / f"{hashlib.sha256(seed.encode()).hexdigest()}.json"

    def _post(self, texts: list[str], kind: Kind) -> list[list[float]]:
        body = json.dumps(
            {
                "model": self.model,
                "texts": texts,
                "input_type": _INPUT_TYPE[kind],
                "embedding_types": ["float"],
                "output_dimension": self.dim,
            }
        ).encode()
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        status = 0
        for attempt in range(_ATTEMPTS):
            status, payload = self._transport(f"{_ORIGIN}v2/embed", headers, body)
            if status == 200:
                vectors = (payload.get("embeddings") or {}).get("float")
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise EmbedError("the embedding service returned the wrong number of vectors")
                if any(len(v) != self.dim for v in vectors):
                    raise EmbedError(f"the embedding service returned the wrong dimension (expected {self.dim})")
                return [[float(x) for x in v] for v in vectors]
            if status not in (429, 500, 502, 503, 504):
                break
            self._sleep(10.0 * (attempt + 1) if status == 429 else 2.0**attempt)
        # the provider's message describes the request; the key is never part of it
        raise EmbedError(f"embedding failed with HTTP {status}")

    def embed(self, texts: Sequence[str], kind: Kind) -> list[list[float]]:
        out: list[list[float] | None] = [None] * len(texts)
        missing: list[int] = []
        for i, text in enumerate(texts):
            path = self._path(text, kind)
            if path is not None and path.exists():
                out[i] = json.loads(path.read_text())
            else:
                missing.append(i)
        for start in range(0, len(missing), _BATCH):
            chunk = missing[start : start + _BATCH]
            for i, vector in zip(chunk, self._post([texts[i] for i in chunk], kind), strict=True):
                out[i] = vector
                path = self._path(texts[i], kind)
                if path is not None:
                    path.write_text(json.dumps(vector))
        return [v for v in out if v is not None]
