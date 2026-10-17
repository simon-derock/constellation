import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from constellation._vendor.orgforge_causal import _EXPLICIT_CAUSAL_LINKS, _SILENCE_PAIRS
from constellation.agents.llm import Reply

RESPONSE_TYPES = sorted({response for _trigger, response, _field in _SILENCE_PAIRS})
MECHANISMS = sorted(_EXPLICIT_CAUSAL_LINKS)
_RESULT_CHARS = 2_500


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


_EVENT = {"type": "string"}
_TYPE = {"type": "string"}
# what each mechanism label means, from the cause and effect types it links in the Apex graph
MECH_GLOSS = {
    "involves_gap": "gap from a departed person's undocumented expertise -> incident",
    "doc_gap_detected": "gap an author found in their own design doc -> incident",
    "async_gap_detected": "async Slack thread exposed a knowledge gap",
    "pr_gap_detected": "PR review exposed a knowledge gap",
    "spawned_doc": "design discussion -> Confluence page",
    "postmortem_from_incident": "incident -> postmortem page",
    "incident_coordination": "incident -> contact with an external party",
    "recurrence_of": "incident repeating an earlier incident",
    "jira_from_vendor_email": "vendor email -> Jira ticket",
    "review_triggers_revision": "PR review requesting changes -> revision review",
    "departure_reassignment": "employee departure -> ticket and escalation reassignment",
    "hire_fills_knowledge_gap": "new hire fills a departed person's knowledge gap",
    "escalation_from_zendesk": "Zendesk escalation -> incident",
}
SPECS = {
    "find_events": _spec(
        "find_events",
        "Events on a day by type; named people rank first.",
        {"day": {"type": "integer"}, "event_type": _TYPE, "actors": {"type": "array", "items": {"type": "string"}}},
        ["day"],
    ),
    "candidate_links": _spec(
        "candidate_links",
        "Cause->effect links from events on a day. A mechanism fixes the types; else event_type/target_type filter. "
        "Rows: cause, mechanism, effect, why.",
        {
            "day": {"type": "integer"},
            "event_type": _TYPE,
            "people": {"type": "array", "items": {"type": "string"}},
            "target_type": _TYPE,
            "mechanism": {"type": "string", "enum": sorted(MECH_GLOSS)},
        },
        ["day"],
    ),
    "could_have_known": _spec(
        "could_have_known", "Could the actor have known this event by the as-of day?", {"event": _EVENT}, ["event"]
    ),
    "counterfactual": _spec(
        "counterfactual",
        "Would removing the cause change the effect, via this mechanism?",
        {"cause": _EVENT, "effect": _EVENT, "mechanism": {"type": "string", "enum": sorted(MECH_GLOSS)}},
        ["cause", "effect", "mechanism"],
    ),
    "absence": _spec(
        "absence",
        "Did the response event follow the trigger? Returns every artifact searched.",
        {"trigger": _EVENT, "response_type": {"type": "string", "enum": RESPONSE_TYPES}},
        ["trigger", "response_type"],
    ),
}
TOOLSETS = {
    "PERSPECTIVE": ("find_events", "could_have_known"),
    "COUNTERFACTUAL": ("candidate_links", "counterfactual"),
    "SILENCE": ("find_events", "absence"),
}


def specs_for(qtype: str, vocabulary: Sequence[str] | None = None) -> list[dict[str, Any]]:
    # event types are an enum of what the graph holds, so a plan cannot name a type that does not exist
    specs = [json.loads(json.dumps(SPECS[name])) for name in TOOLSETS[qtype]]
    if vocabulary:
        options = ["", *vocabulary]
        for spec in specs:
            props = spec["function"]["parameters"]["properties"]
            for field_name in ("event_type", "target_type"):
                if field_name in props:
                    props[field_name]["enum"] = options
    return specs


# the verifier fills mechanism, actors, evidence and reasoning from tool results, so the model emits only the verdict
SCHEMAS = {
    "PERSPECTIVE": '{"could_actor_have_known": bool}',
    "COUNTERFACTUAL": '{"outcome_changed": bool}',
    "SILENCE": '{"exists": bool}',
}
_BASE = (
    "ReAct loop. Each turn: Thought (under 15 words: known, missing), then one Action (one tool call). "
    "Read the Observation before the next Thought. Never repeat an Action, never guess; once the decisive tool "
    "has answered, reply with only the JSON verdict."
)
PROCESS = {
    "PERSPECTIVE": "Action 1: find_events for the event the question names. Action 2: could_have_known on it.",
    "SILENCE": (
        "Action 1: find_events for the trigger event. Action 2: absence(trigger, response_type) for the response "
        "that may be missing."
    ),
    "COUNTERFACTUAL": (
        "Action 1: candidate_links(day, people, mechanism); name the mechanism the wording implies (it fixes the event "
        "types), then pick the row whose why matches the question. Action 2: counterfactual with that row's ids. "
        "Mechanisms: " + "; ".join(f"{name}={gloss}" for name, gloss in MECH_GLOSS.items()) + "."
    ),
}
# counterfactuals and the others are two Actions deep; the rest is slack for one correction
STEP_BUDGET = {"PERSPECTIVE": 5, "SILENCE": 5, "COUNTERFACTUAL": 6}


def system_prompt(q: Question) -> str:
    text = f"{_BASE}\n{PROCESS[q.qtype]}"
    if q.qtype == "PERSPECTIVE":
        text += f"\nYou answer as {q.actor} on Day {q.day} (credentials: {', '.join(q.subsystems)}); stay within it."
    return text


def compact(value: object, limit: int) -> str:
    # observations are evidence, not prose: no padding whitespace, and a hard cap
    return json.dumps(value, separators=(",", ":"), default=str)[:limit]


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
    vocabulary = getattr(tools, "event_types", None)
    specs = specs_for(q.qtype, vocabulary() if callable(vocabulary) else None)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(q)},
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
            content = '{"error":"repeat; reuse the earlier Observation"}'
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
        return compact({"error": str(err)}, 300)
    run.results.append((name, args, result))
    return compact(result, _RESULT_CHARS)


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
