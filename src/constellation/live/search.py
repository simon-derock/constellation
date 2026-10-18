import re
from dataclasses import dataclass
from typing import Any

from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.live.embed import Embedder, EmbedError
from constellation.live.graph import LiveGraph
from constellation.retrieval.fusion import reciprocal_rank_fusion

_WORD = re.compile(r"[A-Za-z0-9_]+")
_MAX_TERMS = 12
_POOL = 30
_PRECISION = 6
_STOP = frozenset(
    (
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "him",
        "his",
        "how",
        "its",
        "may",
        "new",
        "now",
        "old",
        "see",
        "two",
        "way",
        "who",
        "did",
        "get",
        "let",
        "put",
        "say",
        "she",
        "too",
        "use",
        "why",
        "does",
        "what",
        "when",
        "where",
        "which",
        "with",
        "this",
        "that",
        "from",
        "have",
        "been",
        "into",
        "than",
        "them",
        "then",
        "there",
        "these",
        "they",
        "will",
        "would",
        "could",
        "should",
        "about",
        "after",
        "again",
        "also",
        "because",
        "before",
        "being",
        "between",
        "both",
        "each",
        "other",
        "over",
        "some",
        "such",
        "only",
        "same",
        "under",
        "very",
    )
)


def text_query(question: str) -> str:
    # words only, joined with OR: a natural question must still match a title that shares just some of its words, and
    # search operators typed into the box must never reach the index
    seen: dict[str, None] = {}
    for word in _WORD.findall(question.lower()):
        if len(word) >= 3 and word not in _STOP:
            seen.setdefault(word)
    return "|".join(list(seen)[:_MAX_TERMS])


@dataclass(frozen=True, slots=True)
class Hit:
    item: str
    title: str
    repo: str
    via: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Search:
    hits: list[Hit]
    proof: list[dict[str, Any]]
    vector_used: bool


def embed_pending(graph: LiveGraph, embedder: Embedder, limit: int, batch: int = 96) -> int:
    # vectors are made only for items that have none or whose title changed, a batch at a time, so a sync costs one
    # small call when little changed
    done = 0
    while done < limit:
        pending = graph.pending_embeddings(min(batch, limit - done))
        if not pending:
            break
        vectors = embedder.embed([title for _, title in pending], "document")
        graph.set_embeddings([(i, t, v) for (i, t), v in zip(pending, vectors, strict=True)])
        done += len(pending)
    return done


def hybrid_search(port: ReadPort, graph: str, question: str, embedder: Embedder | None, k: int = 10) -> Search:
    # two arms inside the engine, fused by rank: the HNSW index finds items near the question's meaning, the full-text
    # index finds items sharing its words. Each arm that runs is a catalogue query with a hash, so the search replays
    arms: dict[str, list[tuple[str, str, str]]] = {}
    proof: list[dict[str, Any]] = []
    vector_used = False
    # a question with no word in it ("?!") has no meaning to embed: without this guard the nearest vectors to noise
    # would come back as if they were answers
    if not _WORD.search(question):
        return Search([], [], False)
    if embedder is not None:
        try:
            vector = [round(x, _PRECISION) for x in embedder.embed([question], "query")[0]]
        except EmbedError:
            vector = []
        if vector:
            params: dict[str, object] = {"vector": vector, "k": _POOL}
            got = port.run(graph, cypher("live_search_vector"), params)
            arms["vector"] = [(str(r[0]), str(r[1]), str(r[2])) for r in got.rows]
            proof.append({"name": "live_search_vector", "params": params, "sha256": got.sha256})
            vector_used = True
    words = text_query(question)
    if words:
        params = {"query": words, "limit": _POOL}
        got = port.run(graph, cypher("live_search_text"), params)
        arms["text"] = [(str(r[0]), str(r[1]), str(r[2])) for r in got.rows]
        proof.append({"name": "live_search_text", "params": params, "sha256": got.sha256})
    details = {item: (title, repo) for rows in arms.values() for item, title, repo in rows}
    ranked = reciprocal_rank_fusion([[i for i, _, _ in rows] for rows in arms.values()], k=10)[:k]
    via = {item: tuple(name for name, rows in arms.items() if item in {i for i, _, _ in rows}) for item in ranked}
    hits = [Hit(item, details[item][0], details[item][1], via[item]) for item in ranked]
    return Search(hits, proof, vector_used)
