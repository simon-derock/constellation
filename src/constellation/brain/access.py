from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

# Ported from OrgForge eval/eval_harness.py @ 1da5e4b (MIT): the access model that generated Apex.
# Changing a table here scores against a different benchmark (ADR-0005).

# eval_harness.py:174 — artifact key → subsystem; keys missing here never enter a cone
ARTIFACT_SUBSYSTEM: Mapping[str, str] = {
    "jira": "jira",
    "confluence": "confluence",
    "slack": "slack",
    "pr": "git",
    "email": "email",
    "zd_ticket": "zendesk",
    "sf_opp": "salesforce",
    "sf_account": "salesforce",
    "datadog": "datadog",
    "zoom": "zoom",
    "invoice": "email",
    "nps": "salesforce",
    "hr_email": "email",
    "jira_comment": "jira",
    "slack_thread": "slack",
}

_ENGINEERING = frozenset({"slack", "jira", "confluence", "git", "zoom", "email", "datadog"})

# eval_harness.py:134 — role → subsystems the role can open
ROLE_SUBSYSTEM_ACCESS: Mapping[str, frozenset[str]] = {
    "ceo": frozenset({"slack", "jira", "confluence", "zoom", "email", "salesforce", "zendesk", "datadog"}),
    "product": frozenset({"slack", "jira", "confluence", "zoom", "email"}),
    "engineering_backend": _ENGINEERING,
    "engineering_mobile": _ENGINEERING,
    "design": frozenset({"slack", "confluence", "zoom", "email"}),
    "sales_marketing": frozenset({"slack", "salesforce", "email", "zoom", "confluence"}),
    "hr_ops": frozenset({"slack", "email", "confluence", "zoom"}),
    "qa_support": frozenset({"slack", "zendesk", "confluence", "email"}),
    "external": frozenset(),
}

# eval_harness.py:264 — event types whose artifacts reach everyone who can open one of these channels
BROADCAST_CONFIG: Mapping[str, frozenset[str]] = {
    "incident_opened": frozenset({"slack", "datadog"}),
    "incident_resolved": frozenset({"slack"}),
    "postmortem_created": frozenset({"slack", "confluence"}),
    "standup": frozenset({"slack"}),
    "pr_opened": frozenset({"git"}),
    "pr_merged": frozenset({"git"}),
    "knowledge_gap_detected": frozenset({"slack", "confluence"}),
}

_ALL_ROLES = frozenset(ROLE_SUBSYSTEM_ACCESS) - {"external"}

# agentic_eval_harness-v2.py:274 — Jira project prefix → roles; unknown prefixes are unrestricted
JIRA_PROJECT_ACCESS: Mapping[str, frozenset[str]] = {
    "ENG": frozenset({"engineering_backend", "engineering_mobile", "ceo"}),
    "HR": frozenset({"hr_ops", "ceo"}),
    "SALES": frozenset({"sales_marketing", "ceo"}),
    "PROD": frozenset({"product", "ceo"}),
    "DES": frozenset({"design", "product", "ceo"}),
    "QA": frozenset({"qa_support", "ceo"}),
    "ORG": _ALL_ROLES,
}


@dataclass(frozen=True, slots=True)
class SimEvent:
    day: int
    type: str
    actors: tuple[str, ...]
    # (artifact key, artifact id) pairs in source order
    artifact_ids: tuple[tuple[str, str], ...]
    event_id: str = ""
    spawned_doc: bool = False


# eval_harness.py:333 _safe_artifact_values — on-disk paths are not artifacts anyone reads
_DISK_ONLY_KEYS = frozenset({"eml_path", "zoom_path", "transcript_path"})


def event_artifacts(event: SimEvent) -> frozenset[str]:
    return frozenset(aid for key, aid in event.artifact_ids if key not in _DISK_ONLY_KEYS and aid)


def born_days(events: Iterable[SimEvent]) -> dict[str, int]:
    # Apex has one clock, the simulation day; free-text timestamps drift from it in both directions,
    # so an artifact exists from the day of the earliest event that produced it (ADR-0005)
    born: dict[str, int] = {}
    for event in events:
        for aid in event_artifacts(event):
            born[aid] = min(born.get(aid, event.day), event.day)
    return born


def subsystem_access(role: str) -> frozenset[str]:
    return ROLE_SUBSYSTEM_ACCESS.get(role, frozenset())


def jira_project_visible(ticket_id: str, role: str) -> bool:
    prefix = ticket_id.split("-")[0] if "-" in ticket_id else ""
    allowed = JIRA_PROJECT_ACCESS.get(prefix)
    return allowed is None or role in allowed


def visible_artifacts(events: Iterable[SimEvent], actor: str, role: str, as_of_day: int) -> frozenset[str]:
    # the oracle the graph query must match bit for bit (eval_harness.py ActorVisibilityBuilder.build_all)
    access = subsystem_access(role)
    seen: set[str] = set()
    for event in events:
        # cones accumulate over business days 1..as_of_day; earlier history is outside every cone
        if not 1 <= event.day <= as_of_day:
            continue
        direct = actor in event.actors
        channels = BROADCAST_CONFIG.get(event.type)
        broadcast = channels is not None and not channels.isdisjoint(access)
        if not (direct or broadcast):
            continue
        for key, artifact_id in event.artifact_ids:
            if artifact_id and ARTIFACT_SUBSYSTEM.get(key, "default") in access:
                seen.add(artifact_id)
    return frozenset(seen)


def _jira_visible_cone(cone: frozenset[str], role: str) -> frozenset[str]:
    # eval_harness.py _find_asymmetry_events: project-gated tickets drop out of the cone
    return frozenset(
        aid
        for aid in cone
        if not (any(aid.startswith(p + "-") for p in JIRA_PROJECT_ACCESS) and not jira_project_visible(aid, role))
    )


def could_have_known(
    events: Sequence[SimEvent],
    born: Mapping[str, int],
    actor: str,
    role: str,
    target: SimEvent,
    as_of_day: int,
    corpus_artifacts: frozenset[str],
) -> bool:
    # eval_harness.py _find_asymmetry_events + _build_perspective_question, on the simulation-day clock
    cone = _jira_visible_cone(visible_artifacts(events, actor, role, as_of_day), role)
    produced = event_artifacts(target)
    missed = {aid for aid in produced - cone if born.get(aid, as_of_day) <= as_of_day}
    if not missed:
        return True
    # knowledge also travels through an earlier event the actor took part in that shares an artifact
    for event in events:
        if event.day > target.day or actor not in event.actors:
            continue
        overlap = event_artifacts(event) & produced
        if any(aid in cone and born.get(aid, as_of_day + 1) <= as_of_day for aid in overlap):
            return True
    # a design discussion whose page was published is discoverable by anyone who can open Confluence
    page = dict(target.artifact_ids).get("confluence")
    return bool(
        target.type == "design_discussion"
        and target.spawned_doc
        and page in corpus_artifacts
        and "confluence" in subsystem_access(role)
    )
