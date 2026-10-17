import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from constellation._vendor.orgforge_causal import _EXPLICIT_CAUSAL_LINKS, _SILENCE_PAIRS
from constellation.agents.llm import Reply

RESPONSE_TYPES = sorted({response for _trigger, response, _field in _SILENCE_PAIRS})
MECHANISMS = sorted(_EXPLICIT_CAUSAL_LINKS)
# tool results are evidence, not prose: long lists are cut so one call cannot flood the context
_RESULT_CHARS = 4_000


class LLM(Protocol):
    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply: ...


@dataclass(frozen=True, slots=True)
class Question:
    qid: str
    qtype: str
    text: str
    # PERSPECTIVE only: whose knowledge, as of which day, with which credentials
    actor: str = ""
    day: int = 0
    subsystems: tuple[str, ...] = ()


@dataclass
class AgentRun:
    answer: dict[str, Any]
    stop_reason: str
    steps: int = 0
    refused_repeats: int = 0
    tool_errors: int = 0
    protocol_corrections: int = 0
    strategy_changes: list[str] = field(default_factory=list)
    results: list[tuple[str, dict[str, Any], Any]] = field(default_factory=list)


def _spec(name: str, description: str, properties: dict[str, Any], required: Sequence[str]) -> dict[str, Any]:
    schema = {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


_EVENT = {"type": "string", "description": "event id returned by find_events"}
SPECS = {
    "find_events": _spec(
        "find_events",
        "Find simulation events on a day, optionally by event type. Named people rank events: first those "
        "directly involved, then those linked through a shared artifact (a doc they wrote, a thread). "
        "Returns ids and summaries.",
        {
            "day": {"type": "integer", "description": "simulation day number"},
            "event_type": {"type": "string", "description": "e.g. incident_opened, design_discussion; '' for any"},
            "actors": {"type": "array", "items": {"type": "string"}, "description": "names that must all be involved"},
        },
        ["day"],
    ),
    "event_artifacts": _spec(
        "event_artifacts",
        "Artifacts (tickets, pages, threads, emails) an event produced.",
        {"event": _EVENT},
        ["event"],
    ),
    "could_have_known": _spec(
        "could_have_known",
        "Whether the actor could have known about an event by the as-of day, with in-cone evidence artifacts.",
        {"event": _EVENT},
        ["event"],
    ),
    "causal_links": _spec(
        "causal_links",
        "Explicit causal links into and out of an event, with their mechanism.",
        {"event": _EVENT},
        ["event"],
    ),
    "counterfactual": _spec(
        "counterfactual",
        "Would removing the cause event have changed the effect event under this mechanism?",
        {"cause": _EVENT, "effect": _EVENT, "mechanism": {"type": "string", "enum": MECHANISMS}},
        ["cause", "effect", "mechanism"],
    ),
    "absence": _spec(
        "absence",
        "Did an expected response event follow a trigger event? Returns the decision and every artifact searched.",
        {"trigger": _EVENT, "response_type": {"type": "string", "enum": RESPONSE_TYPES}},
        ["trigger", "response_type"],
    ),
}
TOOLSETS = {
    "PERSPECTIVE": ("find_events", "could_have_known", "event_artifacts"),
    "COUNTERFACTUAL": ("find_events", "event_artifacts", "causal_links", "counterfactual"),
    "SILENCE": ("find_events", "event_artifacts", "absence"),
}
SCHEMAS = {
    "PERSPECTIVE": '{"could_actor_have_known": bool, "reasoning": "str", "evidence_artifacts": ["id"], '
    '"blocked_subsystems": ["str"]}',
    "COUNTERFACTUAL": '{"outcome_changed": bool, "causal_mechanism": "<mechanism>", "mechanism": "str", '
    '"actors": ["name"], "reasoning": "str"}',
    "SILENCE": '{"exists": bool, "answer": "yes|no", "reasoning": "what you searched and found"}',
}
_BASE = (
    "You answer questions about a company from its records using tools. Call exactly one tool at a time, never "
    "repeat a call, cite artifact ids, never guess, and finish with only the requested JSON object."
)
PROCESS = {
    "PERSPECTIVE": (
        "Find the event with find_events using the day and event type the question names; summaries help you pick. "
        "Then call could_have_known on that event and answer from its result."
    ),
    "COUNTERFACTUAL": (
        "Find the cause event with find_events; summaries help you pick. Call causal_links on it to see its effects "
        "and mechanisms, and choose the effect the question describes. Then call event_artifacts on the cause, then "
        "on the effect, then counterfactual with that mechanism. Report the mechanism label and the people involved."
    ),
    "SILENCE": (
        "Find the trigger event with find_events and read its artifacts with event_artifacts. Look for the expected "
        "response directly with find_events on the trigger's day and the response's event type, then call absence "
        "with the expected response type. Report every artifact you searched."
    ),
}
# counterfactuals need two events, their artifacts in order, the mechanism and the verdict
STEP_BUDGET = {"PERSPECTIVE": 6, "SILENCE": 6, "COUNTERFACTUAL": 10}


def _system(q: Question) -> str:
    text = f"{_BASE}\n{PROCESS[q.qtype]}"
    if q.qtype == "PERSPECTIVE":
        text += (
            f"\nYou answer as {q.actor} on Day {q.day}, with credentials for {', '.join(q.subsystems)}. "
            "Using information this person could not have had is a violation."
        )
    return text


def _parse(content: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _execute(tools: object, name: str, args: Mapping[str, Any], allowed: Sequence[str]) -> Any:
    if name not in allowed:
        raise PermissionError(f"tool {name} is not available for this question")
    method: Callable[..., Any] = getattr(tools, name)
    return method(**args)


def answer(llm: LLM, tools: object, q: Question, max_steps: int | None = None) -> AgentRun:
    allowed = TOOLSETS[q.qtype]
    specs = [SPECS[n] for n in allowed]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system(q)},
        {"role": "user", "content": f"{q.text}\n\nRespond with JSON:\n{SCHEMAS[q.qtype]}"},
    ]
    run = AgentRun(answer={}, stop_reason="")
    seen: set[str] = set()
    budget = max_steps or STEP_BUDGET[q.qtype]
    while run.steps < budget:
        reply = llm.chat(messages, specs)
        run.steps += 1
        if not reply.tool_calls:
            parsed = _parse(reply.content)
            if parsed is not None:
                run.answer, run.stop_reason = parsed, "final answer"
                return _verify(run, q)
            if run.protocol_corrections:
                break
            run.protocol_corrections += 1
            messages += [reply.message, {"role": "user", "content": "Reply with only the JSON object."}]
            continue
        # one tool per step, as the benchmark protocol requires; extra calls in one reply are dropped
        tool_call = reply.tool_calls[0]
        name = str(tool_call["function"]["name"])
        raw_args = tool_call["function"].get("arguments") or "{}"
        key = f"{name}:{raw_args}"
        messages.append({**reply.message, "tool_calls": [tool_call]})
        if key in seen:
            run.refused_repeats += 1
            content = json.dumps({"error": "already called with these arguments; reuse the earlier result"})
        else:
            seen.add(key)
            content = _invoke(run, tools, name, raw_args, allowed)
        messages.append({"role": "tool", "tool_call_id": tool_call.get("id", name), "content": content})
        if budget - run.steps == 2:
            # a bounded loop says so before it ends, so the decisive tool is called rather than lost
            messages.append({"role": "user", "content": "Two steps left: call the decisive tool now, then answer."})
    final = llm.chat([*messages, {"role": "user", "content": "Stop using tools. Reply with only the JSON object."}], [])
    run.answer, run.stop_reason = _parse(final.content) or {}, "budget exhausted"
    return _verify(run, q)


def _invoke(run: AgentRun, tools: object, name: str, raw_args: str, allowed: Sequence[str]) -> str:
    try:
        args = json.loads(raw_args)
        result = _execute(tools, name, args, allowed)
    except (PermissionError, KeyError, TypeError, ValueError) as err:
        run.tool_errors += 1
        return json.dumps({"error": str(err)})
    run.results.append((name, args, result))
    return json.dumps(result, default=str)[:_RESULT_CHARS]


def _last(run: AgentRun, name: str) -> tuple[dict[str, Any], Any] | None:
    for tool, args, result in reversed(run.results):
        if tool == name:
            return args, result
    return None


def _verify(run: AgentRun, q: Question) -> AgentRun:
    # the decisive tool's evidence outranks the model's wording; every correction is recorded
    if q.qtype == "SILENCE" and (hit := _last(run, "absence")) and hit[1].get("known_expectation"):
        args, result = hit
        exists, searched = bool(result["exists"]), [str(s) for s in result["searched"]]
        if run.answer.get("exists") is not exists:
            run.strategy_changes.append("verify: exists corrected to the absence tool's decision")
        response = args["response_type"]
        found = (
            f"it exists as {result.get('response_event')}"
            if exists
            else f"no {response} was found, so it does not exist"
        )
        grounded = f"Searched {len(searched)} artifacts ({', '.join(searched)}) for a {response}; {found}."
        run.answer.update(exists=exists, answer="yes" if exists else "no")
        run.answer["reasoning"] = f"{grounded} {run.answer.get('reasoning', '')}".strip()
    if q.qtype == "PERSPECTIVE" and (hit := _last(run, "could_have_known")):
        known = bool(hit[1]["could_actor_have_known"])
        if run.answer.get("could_actor_have_known") is not known:
            run.strategy_changes.append("verify: could_actor_have_known corrected to the visibility rule")
        run.answer.update(could_actor_have_known=known, evidence_artifacts=list(hit[1]["evidence_artifacts"]))
        run.answer["blocked_subsystems"] = list(hit[1].get("blocked_subsystems", []))
    if q.qtype == "COUNTERFACTUAL" and (hit := _last(run, "counterfactual")) and hit[1].get("linked"):
        changed = bool(hit[1]["outcome_changed"])
        if run.answer.get("outcome_changed") is not changed:
            run.strategy_changes.append("verify: outcome_changed corrected to the counterfactual tool")
        run.answer.update(outcome_changed=changed, causal_mechanism=hit[0]["mechanism"])
        run.answer["actors"] = list(hit[1].get("actors", []))
    return run
