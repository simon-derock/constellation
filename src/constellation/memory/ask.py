import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from redis.exceptions import RedisError

from constellation.memory.store import MemoryStore
from constellation.proof import ProofQuery

_log = logging.getLogger("constellation.memory")

# all anonymous traffic shares one principal, so visitors cannot add memory graphs; sessions live inside it
PRINCIPAL = "public"
SESSION_PATTERN = r"^[a-z0-9-]{8,64}$"

_VERDICT = {"SILENCE": "exists", "PERSPECTIVE": "could_actor_have_known", "COUNTERFACTUAL": "outcome_changed"}
# the tool whose result decides each kind, and the flag that says it really decided (None: it always does)
_DECISIVE = {
    "SILENCE": ("absence", "known_expectation"),
    "PERSPECTIVE": ("could_have_known", None),
    "COUNTERFACTUAL": ("counterfactual", "linked"),
}
# the sentences the web shows for a verdict, (false, true); a turn in memory reads the way the answer did
_SAYS = {
    "SILENCE": ("No, it did not happen.", "Yes, it happened."),
    "PERSPECTIVE": ("Could not have known.", "Could have known."),
    "COUNTERFACTUAL": ("The outcome would still have happened.", "The outcome would have changed."),
}


@dataclass(frozen=True, slots=True)
class Asked:
    kind: str
    question: str
    key: str

    @classmethod
    def of(cls, tenant: str, kind: str, question: str, actor: str, day: int) -> Self:
        # two questions are the same question when their words match ignoring case and punctuation and, for a
        # perspective, they are asked from the same person on the same day: that is what changes the answer
        words = " ".join(re.sub(r"[\W_]+", " ", question.casefold()).split())
        scope = f"{actor}@{day}|" if kind == "PERSPECTIVE" else ""
        return cls(kind, question.strip(), f"{tenant}|{kind.lower()}|{scope}{words}")

    @property
    def qid(self) -> str:
        return hashlib.sha256(self.key.encode()).hexdigest()


def seal(hashes: Sequence[str]) -> str:
    # byte for byte what the web computes: length-prefixed hashes joined by "|", so the turn names the drawn seal
    return hashlib.sha256("|".join(f"{len(h)}:{h}" for h in hashes).encode()).hexdigest()


def says(kind: str, verdict: bool) -> str:
    return _SAYS[kind][verdict]


def grounded(kind: str, results: Sequence[tuple[str, dict[str, Any], Any]]) -> bool:
    # an answer worth remembering was decided by the graph, not by the model's wording alone
    tool, flag = _DECISIVE[kind]
    return any(t == tool and (flag is None or bool(isinstance(r, dict) and r.get(flag))) for t, _args, r in results)


def verdict_of(kind: str, answer: Mapping[str, Any]) -> bool | None:
    value = answer.get(_VERDICT[kind])
    return value if isinstance(value, bool) else None


class AskMemory:
    # what Ask remembers about a visitor's session, in the public principal's graph
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self.graph = store.provision(PRINCIPAL)

    def learn(
        self,
        session: str,
        asked: Asked,
        results: Sequence[tuple[str, dict[str, Any], Any]],
        answer: Mapping[str, Any],
        queries: Sequence[ProofQuery],
    ) -> None:
        decided = verdict_of(asked.kind, answer)
        if decided is None or not queries or not grounded(asked.kind, results):
            return
        try:
            self._record(session, asked, decided, queries)
        except RedisError:
            # memory is an addition to an answer already in hand: losing it must not lose the answer
            _log.warning("memory write failed; the answer is returned without it", exc_info=True)

    def _record(self, session: str, asked: Asked, decided: bool, queries: Sequence[ProofQuery]) -> None:
        hashes = [q.sha256 for q in queries]
        # a user turn carries its question's id, so a session can tell which learned facts are about its own questions
        self._store.append_turn(PRINCIPAL, session, "user", asked.question, proof_id=asked.qid)
        self._store.append_turn(PRINCIPAL, session, "assistant", says(asked.kind, decided), proof_id=seal(hashes))
        canonical = json.dumps({_VERDICT[asked.kind]: decided}, separators=(",", ":"))
        self._store.record_episode(PRINCIPAL, asked.kind, asked.key, canonical, hashes)
        self._store.consolidate(PRINCIPAL)
