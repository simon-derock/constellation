import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from constellation.agents.epistemic import LLM, RESPONSE_TYPES, AgentRun, Question, _parse, _verify, answer

# tier 2 of PLAN_SPEC §11: the model states what to look for; reviewed catalogue calls do the looking
_DAY_RANGE = range(-1_000, 1_001)
_MAX_CANDIDATES = 5
_TARGET = {
    "PERSPECTIVE": "target_type is ''",
    "SILENCE": "event_type is the triggering event; target_type is the expected response that may be missing",
}


class Tools(Protocol):
    def event_types(self) -> list[str]: ...
    def find_events(self, day: int, event_type: str = "", actors: Sequence[str] = ()) -> list[dict[str, Any]]: ...
    def event_artifacts(self, event: str) -> list[dict[str, Any]]: ...
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
        # models often return numeric ids as numbers; ids are compared as text
        match = next((o for o in options if picked is not None and str(o[key]) == str(picked)), None)
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


def solve(llm: LLM, tools: Tools, q: Question) -> AgentRun:
    # PERSPECTIVE and SILENCE resolve in one model call; COUNTERFACTUAL is a ReAct loop over candidate_links.
    # An unresolved plan falls back to the ReAct loop, and the switch is recorded
    planned = None if q.qtype == "COUNTERFACTUAL" else run_planned(llm, tools, q)
    if planned is not None:
        return planned
    fallback = answer(llm, tools, q)
    if q.qtype != "COUNTERFACTUAL":
        fallback.strategy_changes.insert(0, "plan unresolved: switched to the ReAct loop")
    return fallback
