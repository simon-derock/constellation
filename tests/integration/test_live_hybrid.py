from collections.abc import Sequence
from typing import Any

import pytest
from falkordb import FalkorDB

from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.live.embed import EmbedError, Kind
from constellation.live.graph import LiveGraph
from constellation.live.model import item_from_github, plan_changes
from constellation.live.search import embed_pending, hybrid_search
from constellation.proof import ProofQuery, replay

pytestmark = pytest.mark.integration
GRAPH = "brain:live-hybrid"
KEY = "k" * 32
T1 = 1_770_000_000
TITLES = {
    1: "Vector index crashes on restart",
    2: "Replication lag after failover",
    3: "Document the backup procedure",
    4: "Hnsw recall drops with large datasets",
}
AXIS = {"vector": 0, "index": 0, "hnsw": 0, "replication": 1, "failover": 1, "backup": 2, "recall": 0}


class Fake:
    # a stand-in embedder: each word lights one axis, so meaning is controlled by the test
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.calls = fail, 0

    def embed(self, texts: Sequence[str], kind: Kind) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise EmbedError("embedding failed with HTTP 503")
        out = []
        for text in texts:
            v = [0.05, 0.05, 0.05, 0.05]
            for word in text.lower().split():
                if word.strip("?.,") in AXIS:
                    v[AXIS[word.strip("?.,")]] += 1.0
            out.append(v)
        return out


@pytest.fixture
def live(falkordb: FalkorDB) -> LiveGraph:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    graph = LiveGraph(falkordb, WritePort(falkordb), GRAPH)
    items = []
    for n, title in TITLES.items():
        raw: dict[str, Any] = {
            "number": n,
            "title": title,
            "state": "open",
            "user": {"login": f"user{n}", "type": "User"},
            "assignees": [],
            "labels": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "closed_at": None,
        }
        item = item_from_github("o/a", raw, KEY)
        assert item is not None
        items.append(item)
    graph.apply(items, plan_changes({}, items, observed_at=T1))
    graph.ensure_search_indexes(dim=4)
    return graph


def test_pending_items_are_embedded_in_batches_and_then_none_remain(live: LiveGraph) -> None:
    fake = Fake()
    assert embed_pending(live, fake, limit=3, batch=2) == 3
    assert embed_pending(live, fake, limit=10, batch=2) == 1
    assert live.pending_embeddings(10) == []


def test_a_question_finds_items_by_meaning_even_without_a_shared_word(falkordb: FalkorDB, live: LiveGraph) -> None:
    embed_pending(live, Fake(), limit=10)
    # "recall" and "hnsw" share an axis with "vector index" in the stand-in's space, but not a word in the titles
    found = hybrid_search(ReadPort(falkordb), GRAPH, "hnsw recall problem", Fake(), k=3)
    assert found.hits[0].item == "o/a#4"
    assert "vector" in found.hits[0].via
    assert found.vector_used is True


def test_an_item_found_by_both_arms_outranks_one_found_by_one(falkordb: FalkorDB, live: LiveGraph) -> None:
    embed_pending(live, Fake(), limit=10)
    found = hybrid_search(ReadPort(falkordb), GRAPH, "vector index crash", Fake(), k=4)
    top = found.hits[0]
    assert top.item == "o/a#1"
    assert set(top.via) == {"vector", "text"}


def test_when_the_embedder_fails_the_text_arm_still_answers_and_says_so(falkordb: FalkorDB, live: LiveGraph) -> None:
    embed_pending(live, Fake(), limit=10)
    found = hybrid_search(ReadPort(falkordb), GRAPH, "replication failover", Fake(fail=True), k=3)
    assert found.vector_used is False
    assert found.hits[0].item == "o/a#2"
    assert all(h.via == ("text",) for h in found.hits)


def test_without_an_embedder_only_text_is_searched(falkordb: FalkorDB, live: LiveGraph) -> None:
    found = hybrid_search(ReadPort(falkordb), GRAPH, "backup", None, k=3)
    assert [h.item for h in found.hits] == ["o/a#3"]
    assert found.vector_used is False


def test_every_arm_that_ran_leaves_a_proof_that_replays(falkordb: FalkorDB, live: LiveGraph) -> None:
    embed_pending(live, Fake(), limit=10)
    port = ReadPort(falkordb)
    found = hybrid_search(port, GRAPH, "vector index crash", Fake(), k=3)
    assert {q["name"] for q in found.proof} == {"live_search_vector", "live_search_text"}
    queries = [ProofQuery(q["name"], q["params"], q["sha256"]) for q in found.proof]
    assert replay(port, GRAPH, queries).all_match


def test_a_question_with_nothing_searchable_returns_no_hits_and_no_proof(falkordb: FalkorDB, live: LiveGraph) -> None:
    found = hybrid_search(ReadPort(falkordb), GRAPH, "  ?! ", None, k=3)
    assert found.hits == []
    assert found.proof == []


def test_a_question_of_only_punctuation_is_never_embedded(falkordb: FalkorDB, live: LiveGraph) -> None:
    embed_pending(live, Fake(), limit=10)
    fake = Fake()
    found = hybrid_search(ReadPort(falkordb), GRAPH, "?!", fake, k=3)
    assert found.hits == []
    assert fake.calls == 0
