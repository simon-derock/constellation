import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from constellation.agents.epistemic import LLM, RESPONSE_TYPES, AgentRun, Question, _parse, _verify, answer

# tier 2 of PLAN_SPEC §11: the model states what to look for; reviewed catalogue calls do the looking
_DAY_RANGE = range(-1_000, 1_001)
_MAX_CANDIDATES = 5
_MAX_LINKS = 20
_TARGET = {
    "PERSPECTIVE": "target_type is ''",
    "SILENCE": "event_type is the triggering event; target_type is the expected response that may be missing",
    "COUNTERFACTUAL": "event_type is the cause event; target_type is the effect event",
}


class Tools(Protocol):
    def event_types(self) -> list[str]: ...
    def find_events(self, day: int, event_type: str = "", actors: Sequence[str] = ()) -> list[dict[str, Any]]: ...
    def event_artifacts(self, event: str) -> list[dict[str, Any]]: ...
    def causal_links(self, event: str) -> list[dict[str, Any]]: ...
    def counterfactual(self, cause: str, effect: str, mechanism: str) -> dict[str, Any]: ...
    def could_have_known(self, event: str) -> dict[str, Any]: ...
    def absence(self, trigger: str, response_type: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Plan:
    day: int
    event_type: str
    people: tuple[str, ...]
    target_type: str


def _ask(llm: LLM, system: str, user: str) -> dict[str, Any] | None:
    reply = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], [])
    return _parse(reply.content)


def extract_plan(llm: LLM, q: Question, types: Sequence[str]) -> Plan | None:
    targets = set(types) | set(RESPONSE_TYPES)
    frame = f" The question is asked as of Day {q.day}." if q.qtype == "PERSPECTIVE" else ""
    system = (
        "Turn a question about a company's records into a lookup plan. Use only these event types: "
        f"{', '.join(types)}. Responses that may be missing can also be: {', '.join(RESPONSE_TYPES)}.{frame}"
    )
    user = (
        f"{q.text}\n\nRespond with only JSON: "
        '{"day": int, "event_type": "<type>", "people": ["name"], "target_type": "<type or empty>"}'
        f". Here {_TARGET[q.qtype]}."
    )
    for _attempt in range(2):
        plan = _valid_plan(_ask(llm, system, user), types, targets)
        if plan is not None:
            return plan
    return None


def _valid_plan(raw: Mapping[str, Any] | None, types: Sequence[str], targets: set[str]) -> Plan | None:
    # every field is checked against the graph's vocabulary before any lookup runs
    if raw is None:
        return None
    day, kind = raw.get("day"), raw.get("event_type")
    people, target = raw.get("people", []), raw.get("target_type", "")
    if not isinstance(day, int) or day not in _DAY_RANGE or kind not in types or not isinstance(people, list):
        return None
    if target != "" and target not in targets:
        return None
    return Plan(day, str(kind), tuple(str(p) for p in people[:8]), str(target))


def _choose(llm: LLM, q: Question, options: Sequence[Mapping[str, Any]], key: str) -> Mapping[str, Any] | None:
    # one bounded choice among real candidates; an answer outside them is refused and retried once
    if len(options) <= 1:
        return options[0] if options else None
    listing = "\n".join(json.dumps(dict(o), default=str) for o in options)
    for _attempt in range(2):
        raw = _ask(
            llm,
            "Pick the record the question refers to. Answer with only JSON naming one listed id.",
            f'{q.text}\n\nCandidates:\n{listing}\n\nRespond with only JSON: {{"{key}": "<id>"}}',
        )
        picked = raw.get(key) if raw else None
        match = next((o for o in options if o[key] == picked), None)
        if match is not None:
            return match
    return None


def _note(run: AgentRun, name: str, args: dict[str, Any], result: Any) -> Any:
    run.results.append((name, args, result))
    return result


def run_planned(llm: LLM, tools: Tools, q: Question) -> AgentRun | None:
    plan = extract_plan(llm, q, tools.event_types())
    if plan is None:
        return None
    found = tools.find_events(plan.day, plan.event_type, list(plan.people))
    candidates = [c for c in found if not c.get("no_match")]
    run = AgentRun(answer={}, stop_reason="planned")
    if q.qtype == "COUNTERFACTUAL":
        # the link filter is a cheap graph read, so every candidate is examined before any is dropped
        return _counterfactual(llm, tools, q, plan, candidates, run)
    candidates = candidates[:_MAX_CANDIDATES]
    target = _choose(llm, q, candidates, "event")
    if target is None:
        return None
    event = str(target["event"])
    if q.qtype == "PERSPECTIVE":
        result = _note(run, "could_have_known", {"event": event}, tools.could_have_known(event))
        known = "could" if result["could_actor_have_known"] else "could not"
        run.answer = {"reasoning": f"{q.actor} {known} have known about {event} by Day {q.day}."}
        return _verify(run, q)
    tools.event_artifacts(event)
    tools.find_events(plan.day, plan.target_type)
    args = {"trigger": event, "response_type": plan.target_type}
    result = _note(run, "absence", args, tools.absence(event, plan.target_type))
    if not result.get("known_expectation"):
        return None
    return _verify(run, q)


def _counterfactual(
    llm: LLM, tools: Tools, q: Question, plan: Plan, candidates: Sequence[Mapping[str, Any]], run: AgentRun
) -> AgentRun | None:
    viable = [
        link
        for c in candidates
        for link in tools.causal_links(str(c["event"]))
        if link["cause"] == c["event"] and plan.target_type in ("", link["effect_type"])
    ]
    viable = viable[:_MAX_LINKS]
    for i, link in enumerate(viable):
        link["option"] = str(i)
    picked = _choose(llm, q, viable, "option")
    if picked is None:
        return None
    cause, effect, mechanism = str(picked["cause"]), str(picked["effect"]), str(picked["mechanism"])
    tools.event_artifacts(cause)
    tools.event_artifacts(effect)
    args = {"cause": cause, "effect": effect, "mechanism": mechanism}
    result = _note(run, "counterfactual", args, tools.counterfactual(cause, effect, mechanism))
    alternatives = result.get("alternative_causes") or []
    verdict = "would not" if alternatives else "would"
    run.answer = {
        "mechanism": mechanism.replace("_", " "),
        "reasoning": f"{cause} causes {effect} through {mechanism}; removing it {verdict} change the outcome"
        + (f" because {len(alternatives)} independent {mechanism} cause(s) remain." if alternatives else "."),
    }
    return _verify(run, q)


def solve(llm: LLM, tools: Tools, q: Question) -> AgentRun:
    # planned first; the free tool loop is the fallback, and the switch is recorded
    planned = run_planned(llm, tools, q)
    if planned is not None:
        return planned
    fallback = answer(llm, tools, q)
    fallback.strategy_changes.insert(0, "plan unresolved: switched to the free tool loop")
    return fallback
