import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from constellation.actions.store import ActionRecord
from constellation.agents.epistemic import LLM, AgentRun, Question, _spec, compact
from constellation.agents.llm import LLMError
from constellation.agents.toolbox import Toolbox
from constellation.graph.read import Value
from constellation.proof import ProofQuery

_KIND = "file_issue"
_TITLE_MAX = 120
_BODY_MAX = 1_500
_EVIDENCE_MAX = 8
_LISTED_QUERIES = 12
# the first attempt, and one correction after a refusal
_ATTEMPTS = 2

PROPOSE_ACTION = _spec(
    "propose_action",
    "Propose one follow-up for a person to approve; nothing runs until they do. Only when the answer reveals "
    "something that needs follow-up, such as an expected postmortem or ticket that never happened: then propose "
    "creating it. evidence: names or sha256 hashes of this run's queries, at least one.",
    {
        "title": {"type": "string", "maxLength": _TITLE_MAX},
        "body": {"type": "string", "maxLength": _BODY_MAX},
        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": _EVIDENCE_MAX},
    },
    ["title", "body", "evidence"],
)
_SYSTEM = (
    "You have just answered a question from a company's records. You may now propose one follow-up action for a "
    "person to approve; nothing happens until they do. Propose only when the answer reveals something that needs "
    "follow-up: for example a postmortem, ticket or risk flag that should exist but never happened, in which case "
    "propose creating it. If nothing needs follow-up, call no tool and reply NONE. Cite only the queries listed, "
    "by name or sha256, as evidence."
)


class Proposals(Protocol):
    def propose(
        self, kind: str, title: str, body: str, evidence: list[dict[str, Any]], provenance: str = "rule"
    ) -> ActionRecord: ...


@dataclass(kw_only=True)
class ActingToolbox(Toolbox):
    # the Ask path's toolbox: the benchmark's tools plus one that files a proposal. The benchmark builds a plain
    # Toolbox, and no question type lists propose_action, so the ReAct loop can never call it either
    store: Proposals
    # the actions rate limiter; asked only once a proposal is valid and about to be written
    allow: Callable[[], bool]
    proposed: ActionRecord | None = None

    def _evidence(self, evidence: object) -> list[ProofQuery]:
        # evidence is this run's own proofs, so a hash or name the run never produced cannot be cited
        if not isinstance(evidence, list) or not evidence or len(evidence) > _EVIDENCE_MAX:
            raise ValueError(f"evidence must list 1 to {_EVIDENCE_MAX} of this run's query names or sha256 hashes")
        cited: list[ProofQuery] = []
        for item in evidence:
            hits = [q for q in self.queries if item in (q.sha256, q.name)]
            if not hits:
                raise ValueError(f"{str(item)[:64]!r} is not a proof from this run")
            cited += [q for q in hits if q not in cited]
        return cited

    def _checked(self, title: object, body: object, evidence: object) -> tuple[str, str, list[ProofQuery]]:
        if self.proposed is not None:
            raise ValueError("one proposal per question; it has been made")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("title and body must be text")
        subject, detail = " ".join(title.split()), body.strip()
        if not subject or len(subject) > _TITLE_MAX:
            raise ValueError(f"the title must be 1 to {_TITLE_MAX} characters")
        if not detail or len(detail) > _BODY_MAX:
            raise ValueError(f"the body must be 1 to {_BODY_MAX} characters")
        return subject, detail, self._evidence(evidence)

    def propose_action(self, title: str, body: str, evidence: Sequence[str]) -> dict[str, Value]:
        t0 = time.perf_counter()
        shown = {
            "title": str(title)[:_TITLE_MAX],
            "evidence": [str(e)[:64] for e in evidence] if isinstance(evidence, list) else [],
        }
        try:
            subject, detail, cited = self._checked(title, body, evidence)
            if not self.allow():
                raise PermissionError("the proposal rate limit is reached; try again shortly")
        except (ValueError, PermissionError):
            self._record("propose_action", shown, [], [], [], t0, empty=True)
            raise
        hashes = "; ".join(f"{q.name} result hash {q.sha256}" for q in cited)
        text = (
            f"{detail}\n\n- Evidence: {hashes}. Replay them to verify.\n"
            "- Proposed by the agent; a person approves before anything is filed."
        )
        proofs = [{"name": q.name, "params": q.params, "sha256": q.sha256} for q in cited]
        self.proposed = self.store.propose(_KIND, subject, text, proofs, provenance="agent")
        self._record(
            "propose_action", shown, [self.proposed.id], ["action"], [q.sha256 for q in cited], t0, empty=False
        )
        return {"proposed": True, "id": self.proposed.id, "status": self.proposed.status}


def propose_follow_up(llm: LLM, tools: ActingToolbox, q: Question, run: AgentRun) -> ActionRecord | None:
    # a turn after the verified answer, so the answer format is untouched: the model sees its answer and the
    # run's proofs, and may call propose_action once. A refusal comes back as the Observation for one correction
    if not run.answer or not tools.queries:
        return None
    listed = "\n".join(f"- {p.name} {p.sha256}" for p in tools.queries[:_LISTED_QUERIES])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": f"Question: {q.text}\nAnswer: {compact(run.answer, 1_200)}\nQueries run:\n{listed}",
        },
    ]
    for _attempt in range(_ATTEMPTS):
        try:
            reply = llm.chat(messages, [PROPOSE_ACTION])
        except LLMError:
            # the answer stands without a proposal
            return None
        # one tool per step, as in the answer loop; anything other than propose_action is not a proposal
        if not reply.tool_calls or reply.tool_calls[0]["function"]["name"] != "propose_action":
            return None
        call = reply.tool_calls[0]
        messages.append({**reply.message, "tool_calls": [call]})
        try:
            tools.propose_action(**json.loads(call["function"].get("arguments") or "{}"))
        except PermissionError:
            # the limiter says wait; asking the model again would not change that
            return None
        except (TypeError, ValueError) as err:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", "propose_action"),
                    "content": compact({"error": str(err)}, 300),
                }
            )
            continue
        return tools.proposed
    return None
