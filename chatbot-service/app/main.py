"""HTTP API for the FAQ chatbot (SRS IF-11).

Endpoints
---------
GET  /health            status of the knowledge base, matcher and speech model
POST /v1/chat           {"message": "..."} -> reply
POST /v1/chat/voice     multipart "audio" (WAV) -> reply with "transcript"
POST /v1/kb/refresh     called by WordPress when an FAQ entry changes (secret header)

Visitor text and audio are never logged. Run uvicorn with ``--no-access-log``
so client addresses are not written to the server log either.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .asr import EBranchformerTranscriber
from .audio import AudioError, decode_wav, is_silent
from .config import Settings
from .kb import KnowledgeBase, KnowledgeBaseStore
from .matcher import Matcher, build_matcher, effective_threshold
from .privacy import for_matching
from .ratelimit import RateLimiter
from .reporter import UnansweredReporter
from .responder import Reply, decide

log = logging.getLogger("chatbot")

NO_SPEECH_TEXT = "Sorry, I didn't catch that. Please try again closer to the microphone, or type your question."


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


class ChatService:
    """Holds the knowledge base, matcher index, speech model and helpers."""

    def __init__(
        self,
        settings: Settings,
        kb_store: KnowledgeBaseStore | None = None,
        matcher: Matcher | None = None,
        transcriber: EBranchformerTranscriber | None = None,
        reporter: UnansweredReporter | None = None,
    ):
        self.settings = settings
        self.kb_store = kb_store or KnowledgeBaseStore(settings)
        self._matcher = matcher
        self.transcriber = transcriber or EBranchformerTranscriber(settings)
        self.reporter = reporter or UnansweredReporter(settings)
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self._indexed_version: str | None = None
        self._index_lock = asyncio.Lock()

    @property
    def matcher(self) -> Matcher:
        if self._matcher is None:
            self._matcher = build_matcher(self.settings)
        return self._matcher

    @property
    def threshold(self) -> float:
        return effective_threshold(self.settings, self.matcher.name)

    async def knowledge_base(self) -> KnowledgeBase | None:
        kb = await self.kb_store.get()
        if kb is not None and kb.version != self._indexed_version:
            async with self._index_lock:
                if kb.version != self._indexed_version:
                    await run_in_threadpool(self.matcher.index, kb)
                    self._indexed_version = kb.version
        return kb

    async def answer(self, message: str) -> Reply | None:
        kb = await self.knowledge_base()
        if kb is None:
            return None
        started = time.perf_counter()
        query = for_matching(message)
        ranked = await run_in_threadpool(self.matcher.rank, query, 5) if query else []
        reply = decide(
            query,
            kb,
            ranked,
            threshold=self.threshold,
            margin=self.settings.match_margin,
            suggest_ratio=self.settings.suggest_ratio,
        )
        reply.timing_ms["match"] = round((time.perf_counter() - started) * 1000, 1)
        return reply

    def client_id(self, request: Request) -> str:
        if self.settings.trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None, service: ChatService | None = None) -> FastAPI:
    settings = settings or (service.settings if service else Settings.from_env())
    service = service or ChatService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await service.knowledge_base()  # first load and index; failures are retried later
        if settings.asr_enabled and service.transcriber.state == "loading":
            threading.Thread(target=service.transcriber.load, name="asr-load", daemon=True).start()
        yield

    app = FastAPI(title="Organization FAQ chatbot", version=__version__, lifespan=lifespan)
    app.state.service = service
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            max_age=600,
        )

    def finish(reply: Reply, started: float, background: BackgroundTasks, question: str, source: str) -> dict:
        reply.timing_ms["total"] = round((time.perf_counter() - started) * 1000, 1)
        if reply.type == "fallback":
            background.add_task(service.reporter.report, question, source)
        log.info(
            "reply type=%s faq=%s source=%s total_ms=%s", reply.type, reply.faq_id, source, reply.timing_ms["total"]
        )
        return reply.to_dict()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        kb = service.kb_store.current
        return {
            "status": "ok" if kb is not None else "degraded",
            "version": __version__,
            "knowledge_base": {
                "version": kb.version if kb else None,
                "entries": len(kb.entries) if kb else 0,
                "last_error": service.kb_store.last_error,
            },
            "matcher": {"name": service.matcher.name, "threshold": service.threshold},
            "asr": service.transcriber.info(),
        }

    @app.post("/v1/chat")
    async def chat(request: Request, background: BackgroundTasks):
        started = time.perf_counter()
        if not service.limiter.allow(service.client_id(request)):
            return error(429, "rate_limited", "Too many questions in a short time. Please wait a moment.")
        try:
            body = await request.json()
        except ValueError:
            return error(400, "bad_request", 'Send JSON like {"message": "..."}.')
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not message.strip():
            return error(400, "empty_message", "Please type a question.")
        message = message.strip()
        if len(message) > settings.max_message_chars:
            return error(
                400, "message_too_long", f"Please keep questions under {settings.max_message_chars} characters."
            )
        reply = await service.answer(message)
        if reply is None:
            return error(503, "kb_unavailable", "The chatbot is not available right now.")
        return finish(reply, started, background, message, "text")

    @app.post("/v1/chat/voice")
    async def chat_voice(request: Request, background: BackgroundTasks, audio: UploadFile = File(...)):
        started = time.perf_counter()
        if not service.limiter.allow(service.client_id(request)):
            return error(429, "rate_limited", "Too many questions in a short time. Please wait a moment.")
        if not service.transcriber.ready:
            return error(
                503, "voice_unavailable", "Voice questions are not available right now. Please type your question."
            )
        data = await audio.read(settings.asr_max_upload_bytes + 1)
        try:
            samples = decode_wav(
                data,
                max_bytes=settings.asr_max_upload_bytes,
                min_seconds=settings.asr_min_seconds,
                max_seconds=settings.asr_max_seconds,
            )
        except AudioError as exc:
            return error(400, exc.code, exc.message)
        finally:
            del data

        asr_started = time.perf_counter()
        transcript = "" if is_silent(samples) else await run_in_threadpool(service.transcriber.transcribe, samples)
        asr_ms = round((time.perf_counter() - asr_started) * 1000, 1)
        del samples
        if not transcript:
            reply = Reply(type="no_speech", text=NO_SPEECH_TEXT, transcript="")
            reply.timing_ms["asr"] = asr_ms
            return finish(reply, started, background, "", "voice")
        if len(transcript) > settings.max_message_chars:
            transcript = transcript[: settings.max_message_chars]

        reply = await service.answer(transcript)
        if reply is None:
            return error(503, "kb_unavailable", "The chatbot is not available right now.")
        reply.transcript = transcript
        reply.timing_ms["asr"] = asr_ms
        return finish(reply, started, background, transcript, "voice")

    @app.post("/v1/kb/refresh")
    async def refresh(request: Request):
        key = request.headers.get("x-org-chatbot-key", "")
        if not settings.wp_shared_secret or not hmac.compare_digest(key, settings.wp_shared_secret):
            return error(403, "forbidden", "Invalid key.")
        kb = await service.kb_store.reload()
        await service.knowledge_base()
        return {"version": kb.version if kb else None, "entries": len(kb.entries) if kb else 0}

    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn app.main:app_factory --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
