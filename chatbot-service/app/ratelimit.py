"""Per-visitor rate limiting, held in memory only.

Client addresses are hashed with a random per-process salt before they are
used as keys, kept for at most one minute, and never logged or written to
disk. This keeps a free or low-cost host from being exhausted by one client.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int, window_seconds: float = 60.0, max_keys: int = 10_000):
        self.per_minute = per_minute
        self.window = window_seconds
        self.max_keys = max_keys
        self._salt = secrets.token_bytes(16)
        self._hits: dict[str, deque[float]] = {}

    def _key(self, client: str) -> str:
        return hashlib.sha256(self._salt + client.encode()).hexdigest()[:20]

    def allow(self, client: str, now: float | None = None) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic() if now is None else now
        if len(self._hits) > self.max_keys:
            self._prune(now)
        hits = self._hits.setdefault(self._key(client), deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.per_minute:
            return False
        hits.append(now)
        return True

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
            del self._hits[key]
