from __future__ import annotations

import numpy as np

from .conftest import SECRET, speech_like, wav_bytes


def test_health_reports_kb_matcher_and_ebranchformer(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["knowledge_base"]["entries"] == 12
    assert body["matcher"]["name"] == "lexical"
    assert body["asr"]["state"] == "ready"
    assert body["asr"]["encoder"] == "EBranchformerEncoder"


def test_typed_question_gets_stored_answer(client):
    body = client.post("/v1/chat", json={"message": "How can I join your org?"}).json()
    assert body["type"] == "answer"
    assert body["faq_id"] == "101"
    assert body["text"].startswith("[Sample answer]")
    assert "timing_ms" in body and body["timing_ms"]["total"] >= 0


def test_unmatched_question_gets_fallback_and_is_logged_redacted(client, wordpress):
    body = client.post(
        "/v1/chat",
        json={"message": "My name is Juan Dela Cruz, is parking free? juan@mail.com"},
    ).json()
    assert body["type"] == "fallback"
    assert body["email"]["href"].startswith("mailto:")
    assert body["faq_id"] is None
    assert len(wordpress.unanswered) == 1
    logged = wordpress.unanswered[0]
    assert logged["source"] == "text"
    assert "Juan" not in logged["question"] and "juan@mail.com" not in logged["question"]
    assert "[name]" in logged["question"] and "[email]" in logged["question"]


def test_event_fallback_links_to_events_page(client):
    body = client.post("/v1/chat", json={"message": "Is the seminar venue wheelchair accessible?"}).json()
    assert body["type"] == "fallback"
    assert any(link["url"] == "https://example.org/events/" for link in body["links"])
    assert body["email"]["address"] == "events@example.org"


def test_smalltalk_is_not_logged(client, wordpress):
    body = client.post("/v1/chat", json={"message": "hello!"}).json()
    assert body["type"] == "smalltalk"
    assert wordpress.unanswered == []


def test_validation_errors(client):
    assert client.post("/v1/chat", json={"message": "   "}).json()["error"] == "empty_message"
    assert client.post("/v1/chat", json={"message": "x" * 301}).json()["error"] == "message_too_long"
    assert client.post("/v1/chat", content=b"not json", headers={"content-type": "application/json"}).status_code == 400


def test_spoken_question_is_transcribed_then_answered(client, fake_s2t):
    fake_s2t.next_text = "how can i volunteer"
    response = client.post("/v1/chat/voice", files={"audio": ("q.wav", wav_bytes(speech_like()), "audio/wav")})
    body = response.json()
    assert response.status_code == 200, body
    assert body["transcript"] == "how can i volunteer"
    assert body["type"] == "answer" and body["faq_id"] == "102"
    assert "asr" in body["timing_ms"]


def test_silent_recording_gets_no_speech_without_decoding(client, fake_s2t):
    calls_before = fake_s2t.calls
    silent = np.zeros(16_000, dtype=np.float32)
    body = client.post("/v1/chat/voice", files={"audio": ("q.wav", wav_bytes(silent), "audio/wav")}).json()
    assert body["type"] == "no_speech"
    assert fake_s2t.calls == calls_before


def test_spoken_unmatched_question_is_logged_as_voice(client, wordpress, fake_s2t):
    fake_s2t.next_text = "what is the weather tomorrow"
    body = client.post("/v1/chat/voice", files={"audio": ("q.wav", wav_bytes(speech_like()), "audio/wav")}).json()
    assert body["type"] == "fallback"
    assert wordpress.unanswered[-1]["source"] == "voice"


def test_bad_audio_rejected(client):
    response = client.post("/v1/chat/voice", files={"audio": ("q.wav", b"not a wav", "audio/wav")})
    assert response.status_code == 400 and response.json()["error"] == "bad_audio"


def test_voice_unavailable_when_model_not_ready(client, service):
    service.transcriber.state = "loading"
    response = client.post("/v1/chat/voice", files={"audio": ("q.wav", wav_bytes(speech_like()), "audio/wav")})
    assert response.status_code == 503 and response.json()["error"] == "voice_unavailable"


def test_kb_refresh_requires_shared_secret(client, wordpress):
    assert client.post("/v1/kb/refresh").status_code == 403
    assert client.post("/v1/kb/refresh", headers={"X-Org-Chatbot-Key": "wrong"}).status_code == 403
    wordpress.kb["entries"][0]["answer_text"] = "Edited answer."
    wordpress.kb["entries"][0]["answer_html"] = "<p>Edited answer.</p>"
    wordpress.kb["version"] = "sample-2"
    response = client.post("/v1/kb/refresh", headers={"X-Org-Chatbot-Key": SECRET})
    assert response.json() == {"version": "sample-2", "entries": 12}
    # FR-23 AC1: the edited answer is served without redeploying.
    body = client.post("/v1/chat", json={"message": "How do I become a member?"}).json()
    assert body["text"] == "Edited answer."


def test_rate_limit(client, service):
    service.limiter.per_minute = 2
    codes = [client.post("/v1/chat", json={"message": "hi"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_cors_allows_only_configured_origin(client):
    ok = client.options(
        "/v1/chat",
        headers={"Origin": "https://site.example.org", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://site.example.org"
    bad = client.options(
        "/v1/chat",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers
