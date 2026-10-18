from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files

from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort

_MAX_QUERIES = 50
_MAX_TEXT = 512
_MAX_LIST = 64
# a query embedding is part of a proof: it is the only input a vector search has, so it must be replayable
_MAX_VECTOR = 1_024


@dataclass(frozen=True, slots=True)
class ProofQuery:
    # enough to re-run one catalogue query and compare its result byte for byte
    name: str
    params: dict[str, object]
    sha256: str


@dataclass(frozen=True, slots=True)
class ReplayResult:
    name: str
    match: bool
    sha256: str


@dataclass(frozen=True, slots=True)
class ReplayReport:
    results: tuple[ReplayResult, ...]

    @property
    def all_match(self) -> bool:
        return bool(self.results) and all(r.match for r in self.results)


def catalogue_names() -> frozenset[str]:
    # the only queries a proof may name: reviewed files, never caller-supplied text
    listing = files("constellation.graph").joinpath("cypher").iterdir()
    return frozenset(p.name.removesuffix(".cypher") for p in listing if p.name.endswith(".cypher"))


def _plain(value: object) -> object:
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_TEXT:
            raise ValueError("a replay parameter is too long")
        return value
    if (
        isinstance(value, list)
        and len(value) <= _MAX_LIST
        and all(isinstance(v, str) and len(v) <= _MAX_TEXT for v in value)
    ):
        return value
    if (
        isinstance(value, list)
        and 0 < len(value) <= _MAX_VECTOR
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        return value
    raise ValueError("replay parameters must be plain numbers, strings, lists of strings or numeric vectors")


def replay(port: ReadPort, graph: str, queries: Sequence[ProofQuery]) -> ReplayReport:
    if len(queries) > _MAX_QUERIES:
        raise ValueError(f"too many queries in one proof (limit {_MAX_QUERIES})")
    known = catalogue_names()
    for query in queries:
        if query.name not in known:
            raise ValueError(f"unknown catalogue query {query.name[:40]!r}")
    results = []
    for query in queries:
        params = {k: _plain(v) for k, v in query.params.items()}
        got = port.run(graph, cypher(query.name), params)
        results.append(ReplayResult(query.name, got.sha256 == query.sha256, got.sha256))
    return ReplayReport(tuple(results))
