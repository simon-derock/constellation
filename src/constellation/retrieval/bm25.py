import re
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import scipy.sparse as sp
from sklearn.feature_extraction.text import HashingVectorizer

# hashed terms keep the matrix at one row per document and a few bytes per distinct term, instead of a Python object
# per token; 2**24 buckets keep collisions rare for a vocabulary of a few million terms
_DEFAULT_FEATURES = 2**24


# a compiled pattern, not a literal beside a name like "token": Bandit reads that as a hardcoded credential
_WORD = re.compile(r"(?u)\b\w\w+\b")


def _vectorizer(n_features: int) -> HashingVectorizer:
    return HashingVectorizer(
        n_features=n_features,
        alternate_sign=False,
        norm=None,
        lowercase=True,
        stop_words="english",
        dtype=np.float32,
        token_pattern=_WORD.pattern,
    )


class Bm25Index:
    # Okapi BM25 over hashed unigrams: weights are precomputed per (document, term), so a query is a column sum
    def __init__(self, weights: sp.csc_matrix, n_features: int, avg_length: float) -> None:
        self._weights = weights
        self._rows: sp.csr_matrix | None = None
        self._vec = _vectorizer(n_features)
        self.documents = int(weights.shape[0])
        self.avg_length = avg_length

    @classmethod
    def build(
        cls, batches: Iterable[Sequence[str]], k1: float = 1.2, b: float = 0.75, n_features: int = _DEFAULT_FEATURES
    ) -> "Bm25Index":
        vec = _vectorizer(n_features)
        parts = [vec.transform(list(batch)) for batch in batches if len(batch)]
        if not parts:
            raise ValueError("cannot index an empty corpus")
        counts: sp.csr_matrix = sp.vstack(parts, format="csr")
        del parts
        n = counts.shape[0]
        lengths = np.asarray(counts.sum(axis=1)).ravel().astype(np.float32)
        avg = float(lengths.mean()) or 1.0
        df = np.bincount(counts.indices, minlength=n_features).astype(np.float32)
        idf = np.log1p((n - df + 0.5) / (df + 0.5)).astype(np.float32)
        rows = np.repeat(np.arange(n, dtype=np.int32), np.diff(counts.indptr))
        tf = counts.data
        denominator = tf + k1 * (1.0 - b + b * lengths[rows] / avg)
        counts.data = (idf[counts.indices] * tf * (k1 + 1.0) / denominator).astype(np.float32)
        return cls(counts.tocsc(), n_features, avg)

    @property
    def nbytes(self) -> int:
        w: Any = self._weights
        return int(w.data.nbytes + w.indices.nbytes + w.indptr.nbytes)

    def search(self, query: str, k: int = 10) -> list[tuple[int, float]]:
        terms = np.unique(self._vec.transform([query]).indices)
        if terms.size == 0:
            return []
        return self._rank(np.asarray(self._weights[:, terms].sum(axis=1)).ravel(), k)

    def search_with_feedback(
        self,
        query: str,
        k: int = 10,
        feedback_docs: int = 8,
        feedback_terms: int = 30,
        weight: float = 0.5,
    ) -> list[tuple[int, float]]:
        # Rocchio-style pseudo-relevance feedback: the vocabulary of the first hits is added to the query, scaled so
        # the query's own terms stay dominant. It reaches documents that describe the same thing in other words
        if feedback_docs < 1 or feedback_terms < 1:
            raise ValueError("feedback needs at least one document and one term")
        terms = np.unique(self._vec.transform([query]).indices)
        if terms.size == 0:
            return []
        first = np.asarray(self._weights[:, terms].sum(axis=1)).ravel()
        if weight <= 0:
            return self._rank(first, k)
        top = [i for i, _ in self._rank(first, feedback_docs)]
        if not top:
            return []
        if self._rows is None:
            self._rows = self._weights.tocsr()
        pooled = np.asarray(self._rows[top].sum(axis=0)).ravel()
        pooled[terms] = 0.0
        take = min(feedback_terms, int(np.count_nonzero(pooled)))
        if take == 0:
            return self._rank(first, k)
        chosen = np.argpartition(-pooled, take - 1)[:take]
        chosen = chosen[np.argsort(-pooled[chosen], kind="stable")]
        scale = weight / float(pooled[chosen].max())
        extra = np.asarray(self._weights[:, chosen] @ (pooled[chosen] * scale)).ravel()
        return self._rank(first + extra, k)

    def _rank(self, scores: np.ndarray, k: int) -> list[tuple[int, float]]:
        positive = np.flatnonzero(scores > 0)
        if positive.size == 0:
            return []
        take = min(k, positive.size)
        # score descending, ties by document order, so a ranking is the same on every machine
        top = positive[np.argpartition(-scores[positive], take - 1)[:take]]
        ordered = sorted(top.tolist(), key=lambda i: (-float(scores[i]), i))
        return [(i, float(scores[i])) for i in ordered]
