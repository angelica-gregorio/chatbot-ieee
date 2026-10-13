from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.asr import EBranchformerTranscriber
from app.config import Settings
from app.kb import KnowledgeBaseStore
from app.main import ChatService, create_app
from app.matcher import LexicalMatcher
from app.reporter import UnansweredReporter

DATA = Path(__file__).resolve().parents[1] / "eval" / "data"
SAMPLE_KB = DATA / "sample_kb.json"
SECRET = "test-secret"
WP = "https://wp.example.org"


class EBranchformerEncoder:  # same class name ESPnet uses
    pass


class ConformerEncoder:
    pass


class FakeSpeech2Text:
    """Mimics espnet2.bin.s2t_inference.Speech2Text closely enough for the service."""

    kwargs: dict = {}
    next_text = "how do i volunteer"
    encoder_cls = EBranchformerEncoder
    calls = 0

    def __init__(self):
        self.s2t_model = type("Model", (), {"encoder": self.encoder_cls()})()

    @classmethod
    def from_pretrained(cls, model_tag=None, **kwargs):
        cls.kwargs = {"model_tag": model_tag, **kwargs}
        return cls()

    def __call__(self, speech):
        type(self).calls += 1
        assert speech.dtype == np.float32 and speech.ndim == 1
        text = type(self).next_text
        return [(f"<eng><asr> {text}", [], [], text, None)]


class FakeWordPress:
    """Stands in for the plugin's REST API."""

    def __init__(self):
        self.kb = json.loads(SAMPLE_KB.read_text(encoding="utf-8"))
        self.unanswered: list[dict] = []
        self.kb_requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("x-org-chatbot-key") != SECRET:
            return httpx.Response(403, json={"code": "forbidden"})
        if request.method == "GET" and request.url.path == "/wp-json/org-chatbot/v1/kb":
            self.kb_requests += 1
            return httpx.Response(200, json=self.kb)
        if request.method == "POST" and request.url.path == "/wp-json/org-chatbot/v1/unanswered":
            self.unanswered.append(json.loads(request.content))
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(404)


def wav_bytes(samples: np.ndarray, rate: int = 16_000) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def speech_like(seconds: float = 1.5, rate: int = 16_000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        wp_base_url=WP,
        wp_shared_secret=SECRET,
        kb_ttl_seconds=60,
        allowed_origins=["https://site.example.org"],
        matcher="lexical",
        rate_limit_per_minute=100,
    )


@pytest.fixture
def wordpress() -> FakeWordPress:
    return FakeWordPress()


@pytest.fixture
def fake_s2t():
    FakeSpeech2Text.kwargs = {}
    FakeSpeech2Text.next_text = "how do i volunteer"
    FakeSpeech2Text.encoder_cls = EBranchformerEncoder
    FakeSpeech2Text.calls = 0
    return FakeSpeech2Text


@pytest.fixture
def service(settings, wordpress, fake_s2t) -> ChatService:
    client = httpx.AsyncClient(transport=httpx.MockTransport(wordpress.handler))
    transcriber = EBranchformerTranscriber(settings, speech2text_cls=fake_s2t)
    transcriber.load()
    return ChatService(
        settings,
        kb_store=KnowledgeBaseStore(settings, client=client),
        matcher=LexicalMatcher(),
        transcriber=transcriber,
        reporter=UnansweredReporter(settings, client=client),
    )


@pytest.fixture
def client(settings, service):
    with TestClient(create_app(settings, service)) as test_client:
        yield test_client
