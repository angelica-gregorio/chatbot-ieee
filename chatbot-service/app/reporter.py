"""Sends unanswered questions to the WordPress log (SRS FR-23 AC2).

Only the redacted question text and its source (typed or spoken) are sent.
No address, session, user agent or audio leaves the service.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from .config import Settings
from .privacy import redact

log = logging.getLogger(__name__)


class UnansweredReporter:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.settings.report_unanswered and self.settings.unanswered_url and self.settings.wp_shared_secret)

    async def report(self, question: str, source: Literal["text", "voice"]) -> None:
        if not self.enabled:
            return
        payload = {"question": redact(question)[:300], "source": source}
        client = self._client or httpx.AsyncClient(timeout=self.settings.http_timeout_seconds)
        try:
            response = await client.post(
                self.settings.unanswered_url,
                json=payload,
                headers={"X-Org-Chatbot-Key": self.settings.wp_shared_secret},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Could not record unanswered question: %s", type(exc).__name__)
        finally:
            if self._client is None:
                await client.aclose()
