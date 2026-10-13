"""Knowledge base: the approved FAQ entries and fallback contacts (SRS FR-17, FR-21-23).

The WordPress plugin publishes the knowledge base at
``/wp-json/org-chatbot/v1/kb``. The service keeps a copy in memory, refreshes it
every ``KB_TTL_SECONDS`` and immediately when WordPress calls ``/v1/kb/refresh``,
so an edited answer goes live without redeploying (FR-23 AC1).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import nh3

from .config import Settings

log = logging.getLogger(__name__)

ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "ul", "ol", "li", "a"}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_SCHEMES = {"http", "https", "mailto"}

DEFAULT_FALLBACK = (
    "Sorry, I can only answer questions from our FAQ, and I couldn't find an answer "
    "to that one. Please email us and the right team will get back to you."
)
DEFAULT_GREETING = "Hi! Ask me a question about the Organization, its events, or volunteering."


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class Concern:
    key: str
    label: str
    email: str
    keywords: tuple[str, ...] = ()
    links: tuple[Link, ...] = ()


@dataclass(frozen=True)
class FaqEntry:
    id: str
    question: str
    answer_html: str
    answer_text: str
    alt_questions: tuple[str, ...] = ()
    category: str = ""
    concern: str = ""
    url: str = ""
    links: tuple[Link, ...] = ()

    @property
    def variants(self) -> tuple[str, ...]:
        return (self.question, *self.alt_questions)


@dataclass(frozen=True)
class KnowledgeBase:
    version: str
    entries: tuple[FaqEntry, ...]
    concerns: tuple[Concern, ...] = ()
    default_concern: str = "general"
    fallback_message: str = DEFAULT_FALLBACK
    greeting_message: str = DEFAULT_GREETING
    contact_url: str = ""
    loaded_at: float = field(default_factory=time.time)

    def concern(self, key: str) -> Concern | None:
        for concern in self.concerns:
            if concern.key == key:
                return concern
        return None

    def entry(self, entry_id: str) -> FaqEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None


def safe_url(url: Any) -> str:
    """Return the URL if it is http(s) or mailto, else an empty string."""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    scheme = urlparse(url).scheme.lower()
    return url if scheme in ALLOWED_SCHEMES else ""


def sanitize_html(html: str) -> str:
    """Second line of defence; WordPress already runs wp_kses on answers."""
    return nh3.clean(
        html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer",
    ).strip()


def _links(raw: Any) -> tuple[Link, ...]:
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get("url"))
        label = str(item.get("label") or "").strip()
        if url and label:
            out.append(Link(label=label, url=url))
    return tuple(out)


def _strings(raw: Any) -> tuple[str, ...]:
    return tuple(s.strip() for s in raw or [] if isinstance(s, str) and s.strip())


def parse_kb(payload: dict[str, Any]) -> KnowledgeBase:
    """Validate and convert the plugin's JSON payload. Bad entries are skipped."""
    entries = []
    for raw in payload.get("entries") or []:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        answer_html = sanitize_html(str(raw.get("answer_html") or ""))
        answer_text = str(raw.get("answer_text") or "").strip()
        if not question or not (answer_html or answer_text):
            log.warning("Skipping FAQ entry %r: missing question or answer", raw.get("id"))
            continue
        if not answer_html:
            answer_html = sanitize_html(f"<p>{nh3.clean_text(answer_text)}</p>")
        entries.append(
            FaqEntry(
                id=str(raw.get("id")),
                question=question,
                answer_html=answer_html,
                answer_text=answer_text or nh3.clean(answer_html, tags=set()),
                alt_questions=_strings(raw.get("alt_questions")),
                category=str(raw.get("category") or ""),
                concern=str(raw.get("concern") or ""),
                url=safe_url(raw.get("url")),
                links=_links(raw.get("links")),
            )
        )

    concerns = []
    for raw in payload.get("concerns") or []:
        if not isinstance(raw, dict) or not raw.get("key") or not raw.get("email"):
            continue
        concerns.append(
            Concern(
                key=str(raw["key"]),
                label=str(raw.get("label") or raw["key"]),
                email=str(raw["email"]).strip(),
                keywords=_strings(raw.get("keywords")),
                links=_links(raw.get("links")),
            )
        )

    version = str(payload.get("version") or "")
    if not version:
        digest = json.dumps(payload, sort_keys=True, default=str).encode()
        version = hashlib.sha256(digest).hexdigest()[:16]

    return KnowledgeBase(
        version=version,
        entries=tuple(entries),
        concerns=tuple(concerns),
        default_concern=str(payload.get("default_concern") or "general"),
        fallback_message=str(payload.get("fallback_message") or DEFAULT_FALLBACK),
        greeting_message=str(payload.get("greeting_message") or DEFAULT_GREETING),
        contact_url=safe_url(payload.get("contact_url")),
    )


class KnowledgeBaseStore:
    """Holds the current knowledge base and refreshes it in the background."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._kb: KnowledgeBase | None = None
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None
        self.last_error: str | None = None

    @property
    def current(self) -> KnowledgeBase | None:
        return self._kb

    async def _fetch_payload(self) -> dict[str, Any]:
        if self.settings.kb_url:
            client = self._client or httpx.AsyncClient(timeout=self.settings.http_timeout_seconds)
            try:
                response = await client.get(
                    self.settings.kb_url,
                    headers={"X-Org-Chatbot-Key": self.settings.wp_shared_secret},
                )
                response.raise_for_status()
                return response.json()
            finally:
                if self._client is None:
                    await client.aclose()
        if self.settings.kb_file:
            return json.loads(Path(self.settings.kb_file).read_text(encoding="utf-8"))
        raise RuntimeError("No knowledge base source: set WP_BASE_URL or KB_FILE")

    async def reload(self) -> KnowledgeBase | None:
        """Fetch now. On failure keep serving the previous copy."""
        async with self._lock:
            try:
                kb = parse_kb(await self._fetch_payload())
            except Exception as exc:  # network, JSON or file errors
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Knowledge base refresh failed: %s", self.last_error)
                self._fetched_at = time.monotonic()  # back off until next TTL
                return self._kb
            self._kb = kb
            self._fetched_at = time.monotonic()
            self.last_error = None
            log.info("Knowledge base %s loaded with %d entries", kb.version, len(kb.entries))
            return kb

    async def get(self) -> KnowledgeBase | None:
        """Return the current copy; start a background refresh when it is stale."""
        if self._kb is None:
            return await self.reload()
        stale = time.monotonic() - self._fetched_at >= self.settings.kb_ttl_seconds
        if stale and (self._refresh_task is None or self._refresh_task.done()):
            self._refresh_task = asyncio.create_task(self.reload())
        return self._kb
