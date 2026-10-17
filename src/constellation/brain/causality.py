import sys
from collections.abc import Sequence
from dataclasses import dataclass

from constellation._vendor.orgforge_causal import CausalLinkIndexer
from constellation.ingest.apex import RawEvent


@dataclass(frozen=True, slots=True, order=True)
class CausalEdge:
    link_type: str
    cause: str
    effect: str
    day: int


@dataclass(frozen=True, slots=True)
class Counterfactual:
    linked: bool
    changed: bool
    # other causes of the same effect through the same mechanism, sorted
    alternatives: tuple[str, ...]


class _NoDocuments:
    # the indexer reads Mongo only to label recurrence links; labels are not edges, so it is given nothing
    def __getitem__(self, _collection: str) -> "_NoDocuments":
        return self

    def find_one(self, *_args: object, **_kwargs: object) -> None:
        return None


class _Memory:
    _db = _NoDocuments()


def index_causal_links(events: Sequence[RawEvent]) -> list[CausalEdge]:
    indexer = CausalLinkIndexer(list(events), mem=_Memory())
    # the benchmark samples 15 links per type for question generation; the brain keeps every link
    indexer.MAX_LINKS_PER_TYPE = sys.maxsize
    return sorted(
        {CausalEdge(link.link_type, link.cause_event_id, link.effect_event_id, link.day) for link in indexer.build()}
    )


def counterfactual(edges: Sequence[CausalEdge], link_type: str, cause: str, effect: str) -> Counterfactual:
    # removing a cause changes the effect only if no independent cause of the same mechanism remains
    causes = sorted({e.cause for e in edges if e.effect == effect and e.link_type == link_type})
    linked = cause in causes
    alternatives = tuple(c for c in causes if c != cause)
    return Counterfactual(linked=linked, changed=linked and not alternatives, alternatives=alternatives)
