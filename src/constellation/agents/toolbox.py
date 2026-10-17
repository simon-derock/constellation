import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from constellation.brain.access import JIRA_PROJECT_ACCESS, jira_project_visible, subsystem_access
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort, ReadResult, Value


@dataclass(frozen=True, slots=True)
class ToolRecord:
    # one trajectory step: what was asked, which artifacts came back, and the proof hashes behind them
    tool: str
    args: Mapping[str, object]
    result_ids: tuple[str, ...]
    result_types: tuple[str, ...]
    proofs: tuple[str, ...]
    latency_ms: float
    # a dead end: the call found nothing to act on, which the benchmark scores as a recovery opportunity
    empty: bool


@dataclass(frozen=True, slots=True)
class Perspective:
    actor: str
    role: str
    day: int


@dataclass
class Toolbox:
    # graph-backed tools for one question; in a perspective, no artifact outside the actor's cone is ever returned
    port: ReadPort
    graph: str
    perspective: Perspective | None = None
    calls: list[ToolRecord] = field(default_factory=list)

    def _run(self, name: str, params: Mapping[str, object]) -> ReadResult:
        return self.port.run(self.graph, cypher(name), dict(params))

    def _record(
        self,
        tool: str,
        args: Mapping[str, object],
        ids: Sequence[str],
        types: Sequence[str],
        proofs: Sequence[str],
        t0: float,
        empty: bool,
    ) -> None:
        latency = (time.perf_counter() - t0) * 1_000
        self.calls.append(ToolRecord(tool, dict(args), tuple(ids), tuple(types), tuple(proofs), latency, empty))

    def _required_perspective(self) -> Perspective:
        # a guard, not an assert: it must hold under python -O too
        if self.perspective is None:
            raise PermissionError("this tool answers only from an actor's perspective")
        return self.perspective

    def _cone(self) -> tuple[frozenset[str], str]:
        p = self._required_perspective()
        result = self._run("apex_cone", {"actor": p.actor, "day": p.day})
        visible = result.rows[0][0] if result.rows else []
        ids = [str(v) for v in visible] if isinstance(visible, list) else []
        gated = tuple(prefix + "-" for prefix in JIRA_PROJECT_ACCESS)
        return frozenset(i for i in ids if not i.startswith(gated) or jira_project_visible(i, p.role)), result.sha256

    def visible(self) -> frozenset[str]:
        # the cone the tools enforce, exposed so scoring judges against the same boundary
        return self._cone()[0]

    def find_events(self, day: int, event_type: str = "", actors: Sequence[str] = ()) -> list[dict[str, Value]]:
        t0 = time.perf_counter()
        args = {"day": day, "event_type": event_type, "actors": list(actors)}
        result = self._run("find_events", args)
        rows = [dict(zip(result.columns, row, strict=True)) for row in result.rows]
        proofs = [result.sha256]
        if not rows:
            # a failed lookup comes back with the day's event types so the next lookup can be corrected
            kinds = self._run("event_types_on_day", {"day": day})
            rows = [{"no_match": True, "event_types_on_day": [str(r[0]) for r in kinds.rows]}]
            proofs.append(kinds.sha256)
        # events are not artifacts: linking an event reveals no artifact content
        self._record("find_events", args, [], [], proofs, t0, empty="no_match" in rows[0])
        return rows

    def event_artifacts(self, event: str) -> list[dict[str, Value]]:
        t0 = time.perf_counter()
        result = self._run("event_artifacts", {"event": event})
        rows = [dict(zip(result.columns, row, strict=True)) for row in result.rows]
        proofs = [result.sha256]
        if self.perspective is not None:
            cone, cone_proof = self._cone()
            rows = [r for r in rows if r["artifact"] in cone]
            proofs.append(cone_proof)
        self._record(
            "event_artifacts",
            {"event": event},
            [str(r["artifact"]) for r in rows],
            [str(r["key"]) for r in rows],
            proofs,
            t0,
            empty=not rows,
        )
        return rows

    def could_have_known(self, event: str) -> dict[str, Value]:
        # PERSPECTIVE rule (ADR-0005) composed from graph reads; evidence is restricted to the cone
        p = self._required_perspective()
        t0 = time.perf_counter()
        cone, cone_proof = self._cone()
        produced = self._run("event_artifacts", {"event": event})
        info = self._run("event_info", {"event": event})
        shared = self._run("shared_involvement", {"actor": p.actor, "event": event, "day": p.day})
        born = {str(r[0]): r[3] for r in produced.rows}
        made = set(born)
        missed = {a for a in made - cone if _day_or_never(born[a]) <= p.day}
        met = {str(r[0]) for r in shared.rows} & cone
        kind, _day, spawned, page_in_corpus, _actors = info.rows[0] if info.rows else ("", 0, False, False, [])
        published = (
            kind == "design_discussion" and spawned and page_in_corpus and "confluence" in subsystem_access(p.role)
        )
        known = not missed or bool(met) or bool(published)
        evidence = sorted((made & cone) | met)
        # subsystem names, never artifact ids: what the role could not open, which reveals no content
        event_subsystems = {str(r[2]) for r in produced.rows if r[2] != "default"}
        blocked = sorted(event_subsystems - subsystem_access(p.role))
        proofs = [cone_proof, produced.sha256, info.sha256, shared.sha256]
        self._record(
            "could_have_known", {"event": event}, evidence, ["artifact"] * len(evidence), proofs, t0, empty=False
        )
        return {
            "could_actor_have_known": known,
            "evidence_artifacts": list(evidence),
            "blocked_subsystems": list(blocked),
            "missed_count": len(missed),
        }

    def causal_links(self, event: str) -> list[dict[str, Value]]:
        t0 = time.perf_counter()
        result = self._run("causal_links", {"event": event})
        rows = [dict(zip(result.columns, row, strict=True)) for row in result.rows]
        self._record("causal_links", {"event": event}, [], [], [result.sha256], t0, empty=not rows)
        return rows

    def counterfactual(self, cause: str, effect: str, mechanism: str) -> dict[str, Value]:
        t0 = time.perf_counter()
        args = {"cause": cause, "effect": effect, "link_type": mechanism}
        result = self._run("counterfactual", args)
        linked, alternatives = result.rows[0] if result.rows else (False, [])
        alts = [str(a) for a in alternatives] if isinstance(alternatives, list) else []
        people: set[str] = set()
        proofs = [result.sha256]
        for event in (cause, effect):
            info = self._run("event_info", {"event": event})
            proofs.append(info.sha256)
            names = info.rows[0][4] if info.rows else []
            people |= {str(n) for n in names} if isinstance(names, list) else set()
        self._record("counterfactual", args, [], [], proofs, t0, empty=not linked)
        actors: list[Value] = [*sorted(people)]
        return {
            "linked": linked,
            "outcome_changed": bool(linked) and not alts,
            "alternative_causes": list(alts),
            "actors": actors,
        }

    def absence(self, trigger: str, response_type: str) -> dict[str, Value]:
        t0 = time.perf_counter()
        args = {"trigger": trigger, "response_type": response_type}
        result = self._run("absence", args)
        if not result.rows:
            self._record("absence", args, [], [], [result.sha256], t0, empty=True)
            return {"known_expectation": False, "exists": None, "searched": []}
        responded, response_event, searched = result.rows[0]
        space = [str(s) for s in searched] if isinstance(searched, list) else []
        self._record("absence", args, space, ["artifact"] * len(space), [result.sha256], t0, empty=False)
        return {
            "known_expectation": True,
            "exists": responded,
            "response_event": response_event,
            "searched": list(space),
        }


def _day_or_never(value: Value) -> int:
    # an artifact with no recorded birth day has not happened yet, on any horizon
    return value if isinstance(value, int) and not isinstance(value, bool) else 10**9
