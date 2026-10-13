from __future__ import annotations

import json

import numpy as np
import pytest

from app.config import DEFAULT_THRESHOLDS, Settings
from app.kb import parse_kb
from app.matcher import EmbeddingMatcher, LexicalMatcher, build_matcher, coverage, effective_threshold
from app.responder import decide, smalltalk

from .conftest import SAMPLE_KB

LEXICAL_THRESHOLD = DEFAULT_THRESHOLDS["lexical"]


@pytest.fixture(scope="module")
def kb():
    return parse_kb(json.loads(SAMPLE_KB.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def lexical(kb):
    matcher = LexicalMatcher()
    matcher.index(kb)
    return matcher


@pytest.mark.parametrize(
    ("question", "faq_id"),
    [
        ("how do i join your org", "101"),
        ("where can i register for your workshop", "103"),
        ("is there a chapter near me", "107"),
        ("can our company sponsor you", "108"),
        ("what's your contact email", "109"),
    ],
)
def test_lexical_ranks_paraphrases(lexical, question, faq_id):
    ranked = lexical.rank(question)
    assert ranked[0].entry.id == faq_id
    assert ranked[0].score >= LEXICAL_THRESHOLD


@pytest.mark.parametrize(
    "question",
    ["what's the weather tomorrow", "can i transfer my membership to my sibling", "will the workshop be recorded"],
)
def test_lexical_low_score_for_unrelated(lexical, question):
    ranked = lexical.rank(question)
    assert not ranked or ranked[0].score < LEXICAL_THRESHOLD


def test_coverage_weights_unknown_words_heavily():
    weights = {"member": 1.0}
    share = coverage({"member", "sibling"}, {"member"}, lambda token: weights.get(token, 3.0))
    assert share == pytest.approx(0.25)
    assert coverage({"org"}, {"organization"}) == 1.0


def test_lexical_empty_query(lexical):
    assert lexical.rank("the and of") == []


class HashingModel:
    """Deterministic bag-of-words embeddings standing in for sentence-transformers."""

    dim = 64

    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                out[row, hash(word.strip("?.,!")) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


def test_embedding_matcher_uses_best_variant_per_entry(kb):
    matcher = EmbeddingMatcher("fake", model=HashingModel())
    matcher.index(kb)
    ranked = matcher.rank("Are you looking for volunteers?")
    assert ranked[0].entry.id == "102"
    assert ranked[0].score == pytest.approx(1.0, abs=1e-5)
    assert len({item.entry.id for item in ranked}) == len(ranked)


def test_build_matcher_falls_back_to_lexical(monkeypatch):
    def boom(self):
        raise ImportError("sentence_transformers not installed")

    monkeypatch.setattr(EmbeddingMatcher, "load", boom)
    matcher = build_matcher(Settings(matcher="embedding"))
    assert matcher.name == "lexical"


def test_threshold_only_applies_to_its_matcher():
    settings = Settings(matcher="embedding", match_threshold=0.72)
    assert effective_threshold(settings, "embedding") == 0.72
    assert effective_threshold(settings, "lexical") == LEXICAL_THRESHOLD


def test_smalltalk(kb):
    assert smalltalk("Hello!", kb).type == "smalltalk"
    assert smalltalk("good morning po", kb).type == "smalltalk"
    assert smalltalk("salamat", kb).type == "smalltalk"
    assert smalltalk("hi, how do I volunteer?", kb) is None


def test_answer_is_stored_text(kb, lexical):
    reply = decide("how do i join your org", kb, lexical.rank("how do i join your org"), threshold=LEXICAL_THRESHOLD)
    entry = kb.entry("101")
    assert reply.type == "answer"
    assert reply.text == entry.answer_text and reply.html == entry.answer_html


def test_fallback_routes_by_keyword(kb, lexical):
    question = "will the workshop be recorded"
    reply = decide(question, kb, lexical.rank(question), threshold=0.99)
    assert reply.type == "fallback"
    assert reply.email.address == "events@example.org"
    assert reply.email.href == "mailto:events@example.org?subject=Website%20inquiry%3A%20Events"
    assert [link.url for link in reply.links][:1] == ["https://example.org/events/"]
    assert any(link.url == "https://example.org/contact/" for link in reply.links)


def test_fallback_defaults_to_general(kb):
    reply = decide("asdf qwerty", kb, [], threshold=LEXICAL_THRESHOLD)
    assert reply.type == "fallback"
    assert reply.email.address == "info@example.org"
    assert reply.suggestions == []


def test_margin_forces_fallback_when_top_two_are_close(kb, lexical):
    question = "events"
    ranked = lexical.rank(question)
    reply = decide(question, kb, ranked, threshold=0.0, margin=1.0)
    assert reply.type == "fallback"
