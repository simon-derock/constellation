import json
import re
from dataclasses import dataclass

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PASSAGE_MAX = 1_200
_KEYWORDS_MAX = 20

_SYSTEM = (
    "You help search an enterprise knowledge base: Slack threads, emails, Jira tickets, pull requests, Confluence "
    "pages, meeting notes and CRM records of a cloud AI infrastructure company. Questions are often phrased in other "
    "words than the documents use, so you restate them in the documents' own vocabulary."
)

_TASK = (
    "Question: {question}\n\n"
    "Write what the answering document most likely says, using the concrete terms it would use: product and feature "
    "names, abbreviations, error names, regions, numbers and units, and the synonyms of any vague phrase in the "
    "question. Do not answer from memory and do not explain.\n"
    'Reply with JSON only: {{"passage": "<2-4 sentences as the document would phrase them>", '
    '"keywords": ["<up to 15 specific terms and synonyms>"]}}'
)


@dataclass(frozen=True, slots=True)
class Rewrite:
    passage: str
    keywords: tuple[str, ...]


def build_messages(question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _TASK.format(question=question.strip())},
    ]


def _clean(text: str) -> str:
    return _CONTROL.sub("", text).strip()


def _keywords(value: object) -> tuple[str, ...]:
    parts = re.split(r"[,\n;]", value) if isinstance(value, str) else value if isinstance(value, list) else []
    words = (_clean(str(p)) for p in parts)
    return tuple(w for w in words if w)[:_KEYWORDS_MAX]


def parse_rewrite(raw: str) -> Rewrite:
    # models wrap JSON in prose or code fences; anything unparseable is kept as the passage, never silently dropped
    text = _clean(raw)
    if not text:
        return Rewrite("", ())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return Rewrite(_clean(str(data.get("passage", "")))[:_PASSAGE_MAX], _keywords(data.get("keywords")))
    return Rewrite(text[:_PASSAGE_MAX], ())


def search_queries(question: str, rewrite: Rewrite) -> list[tuple[str, str]]:
    # the original question is always searched; the rewrite adds the question's missing vocabulary
    out = [("original", question)]
    if rewrite.passage:
        out.append(("passage", rewrite.passage))
    if rewrite.keywords:
        out.append(("keywords", f"{question} {' '.join(rewrite.keywords)}"))
    return out
