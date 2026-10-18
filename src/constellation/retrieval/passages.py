import math
import re
from collections import Counter
from collections.abc import Mapping

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

_WORD = re.compile(r"(?u)\b\w\w+\b")


def windows(text: str, size: int, stride: int) -> list[str]:
    # overlapping windows that together cover every character, so nothing in a long thread is unreachable
    if not text:
        return []
    out = [text[:size]]
    start = stride
    while start + (size - stride) < len(text):
        out.append(text[start : start + size])
        start += stride
    return out


def _terms(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in ENGLISH_STOP_WORDS}


def best_windows(
    query: str, docs: Mapping[str, str], per_doc: int, size: int = 1_000, stride: int = 800
) -> dict[str, list[str]]:
    # query-focused chunking: the answer is a few sentences inside a long document, so each candidate is represented
    # by its head (titles and headers live there) plus the windows that share the most rare query terms. Rarity is
    # measured over this question's own candidate pool, where it says what separates one near-duplicate from another
    cut = {d: windows(t, size, stride) for d, t in docs.items()}
    wanted = _terms(query)
    sets = {d: [_terms(w) for w in ws] for d, ws in cut.items()}
    pool = sum(len(v) for v in sets.values()) or 1
    freq: Counter[str] = Counter(t for ws in sets.values() for s in ws for t in s & wanted)
    idf = {t: math.log(1 + pool / (1 + freq[t])) for t in wanted}
    out: dict[str, list[str]] = {}
    for d, ws in cut.items():
        scores = [(sum(idf[t] for t in s & wanted), i) for i, s in enumerate(sets[d])]
        # head always; then the best of the rest, ties to the earlier window, returned in document order
        rest = sorted((x for x in scores if x[1] != 0), key=lambda x: (-x[0], x[1]))[: max(per_doc - 1, 0)]
        keep = sorted({0, *(i for score, i in rest if score > 0)})
        out[d] = [ws[i] for i in keep[:per_doc]]
    return out
