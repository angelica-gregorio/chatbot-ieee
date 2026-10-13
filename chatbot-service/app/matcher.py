"""Retrieval over the approved FAQ set (SRS FR-21, A-10).

Two interchangeable matchers rank FAQ entries for a question:

* ``EmbeddingMatcher`` - sentence embeddings (default ``all-MiniLM-L6-v2``),
  cosine similarity against each entry's question and alternate phrasings.
* ``LexicalMatcher`` - TF-IDF over words and character trigrams. No model
  download, so it is the fallback and the baseline for the evaluation.

Neither generates text: the service only ever returns a stored answer or the
fallback reply (FR-22, NFR-SAF-04, OS-06).
"""

from __future__ import annotations

import logging
import math
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .config import DEFAULT_THRESHOLDS, Settings
from .kb import FaqEntry, KnowledgeBase
from .text import char_ngrams, content_tokens

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Scored:
    entry: FaqEntry
    score: float


class Matcher(Protocol):
    name: str

    def index(self, kb: KnowledgeBase) -> None: ...

    def rank(self, query: str, k: int = 5) -> list[Scored]: ...


def _best_per_entry(pairs: list[tuple[int, float]], entries: list[FaqEntry], k: int) -> list[Scored]:
    best: dict[int, float] = {}
    for entry_idx, score in pairs:
        if score > best.get(entry_idx, float("-inf")):
            best[entry_idx] = score
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)[:k]
    return [Scored(entries[idx], float(score)) for idx, score in ranked]


def _same_word(a: str, b: str) -> bool:
    """Equal, or one is a prefix of the other (org/organization, attend/attending)."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long_.startswith(short)


def coverage(query_tokens: set[str], doc_tokens: set[str], weight=lambda token: 1.0) -> float:
    """Weighted share of the question's content words that the FAQ phrasing accounts for."""
    total = sum(weight(q) for q in query_tokens)
    if total <= 0:
        return 0.0
    covered = sum(weight(q) for q in query_tokens if any(_same_word(q, d) for d in doc_tokens))
    return covered / total


class LexicalMatcher:
    """TF-IDF cosine over words and character trigrams, weighted by word coverage.

    Plain cosine lets one shared keyword ("member", "event") carry an
    unrelated question over the threshold. Multiplying by coverage - the
    IDF-weighted share of the question's content words found in the FAQ
    phrasing - means a question about something the FAQ never mentions
    ("transfer my membership to my sibling") scores low even when it shares a
    topic word. Words the FAQ never uses get the highest weight.
    """

    name = "lexical"

    def __init__(self, char_weight: float = 0.5, coverage_power: float = 1.5):
        self.char_weight = char_weight
        self.coverage_power = coverage_power
        self._entries: list[FaqEntry] = []
        self._docs: list[tuple[int, dict[str, float], float, set[str]]] = []
        self._idf: dict[str, float] = {}
        self._max_idf = 1.0

    def _word_weight(self, token: str) -> float:
        return self._idf.get(f"w:{token}", self._max_idf)

    def _features(self, text: str) -> Counter:
        feats: Counter = Counter()
        for token in content_tokens(text):
            feats[f"w:{token}"] += 1.0
        for gram in char_ngrams(text):
            feats[f"c:{gram}"] += self.char_weight
        return feats

    def _vector(self, feats: Counter) -> tuple[dict[str, float], float]:
        vec = {}
        for feat, tf in feats.items():
            idf = self._idf.get(feat)
            if idf is None:
                continue
            vec[feat] = (1.0 + math.log(tf)) * idf if tf >= 1 else tf * idf
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return vec, norm

    def index(self, kb: KnowledgeBase) -> None:
        self._entries = list(kb.entries)
        raw_docs = []
        for idx, entry in enumerate(self._entries):
            for variant in entry.variants:
                raw_docs.append((idx, self._features(variant), set(content_tokens(variant))))
        n_docs = len(raw_docs)
        df: Counter = Counter()
        for _, feats, _ in raw_docs:
            df.update(feats.keys())
        self._idf = {feat: math.log((1 + n_docs) / (1 + count)) + 1.0 for feat, count in df.items()}
        self._max_idf = max(self._idf.values(), default=1.0)
        self._docs = []
        for idx, feats, tokens in raw_docs:
            vec, norm = self._vector(feats)
            if norm > 0:
                self._docs.append((idx, vec, norm, tokens))

    def rank(self, query: str, k: int = 5) -> list[Scored]:
        qvec, qnorm = self._vector(self._features(query))
        qtokens = set(content_tokens(query))
        if qnorm == 0 or not qtokens or not self._docs:
            return []
        pairs = []
        for idx, dvec, dnorm, dtokens in self._docs:
            small, large = (qvec, dvec) if len(qvec) < len(dvec) else (dvec, qvec)
            dot = sum(weight * large.get(feat, 0.0) for feat, weight in small.items())
            if dot > 0:
                cosine = dot / (qnorm * dnorm)
                share = coverage(qtokens, dtokens, self._word_weight)
                pairs.append((idx, cosine * share**self.coverage_power))
        return _best_per_entry(pairs, self._entries, k)


class EmbeddingMatcher:
    """Cosine similarity of sentence embeddings (sentence-transformers)."""

    name = "embedding"

    def __init__(self, model_name: str, model=None):
        self.model_name = model_name
        self._model = model
        self._entries: list[FaqEntry] = []
        self._rows: list[int] = []
        self._matrix = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import

            self._model = SentenceTransformer(self.model_name, device="cpu")

    def _encode(self, texts: list[str]):
        with self._lock:
            return self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)

    def index(self, kb: KnowledgeBase) -> None:
        self.load()
        self._entries = list(kb.entries)
        texts, rows = [], []
        for idx, entry in enumerate(self._entries):
            for variant in entry.variants:
                texts.append(variant)
                rows.append(idx)
        self._rows = rows
        self._matrix = self._encode(texts) if texts else None

    def rank(self, query: str, k: int = 5) -> list[Scored]:
        if self._matrix is None or not query.strip():
            return []
        qvec = self._encode([query])[0]
        sims = self._matrix @ qvec
        pairs = [(self._rows[i], float(s)) for i, s in enumerate(sims)]
        return _best_per_entry(pairs, self._entries, k)


def build_matcher(settings: Settings) -> Matcher:
    """Build the configured matcher, falling back to lexical if the model is missing."""
    if settings.matcher == "embedding":
        matcher = EmbeddingMatcher(settings.embedding_model)
        try:
            matcher.load()
            return matcher
        except Exception as exc:  # ImportError, network or model errors
            log.warning("Embedding matcher unavailable (%s); using lexical matcher", exc)
    return LexicalMatcher()


def effective_threshold(settings: Settings, matcher_name: str) -> float:
    """Use MATCH_THRESHOLD only for the matcher it was calibrated for."""
    if settings.match_threshold is not None and matcher_name == settings.matcher:
        return settings.match_threshold
    return DEFAULT_THRESHOLDS.get(matcher_name, 0.5)
