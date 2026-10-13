"""Redaction for the unanswered-question log (SRS FR-23 AC2, NFR-CMP-01).

The log may keep the question text, date and count, but never a name, email
or other identifier. Visitors sometimes type these into the chat, so they are
masked before anything leaves the service. WordPress applies the same rules
again on receipt.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_URL = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
# Philippine mobile (09xx / +639xx) and landline formats, plus long digit runs
# such as student or government ID numbers.
_PHONE = re.compile(r"(?:\+?63|0)[\s.-]?9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b")
_LANDLINE = re.compile(r"\(?\b0?2\)?[\s.-]?\d{3,4}[\s.-]?\d{4}\b")
_LONG_NUMBER = re.compile(r"\b\d[\d\s-]{5,}\d\b")
# "my name is Juan Dela Cruz", "I'm Ana", "ako si Ana", "this is Mark"
_NAME_INTRO = re.compile(
    r"\b((?i:my name is|my name's|i am|i'm|im|this is|ako si|ako po si|pangalan ko ay))\s+"
    r"((?:[A-Z][\w'-]+)(?:\s+(?:de|dela|del|delos|van|von|[A-Z][\w'-]+)){0,3})",
)
_SECRET_HINT = re.compile(
    r"\b(password|passcode|pin|otp|tin|sss|philhealth|pag-?ibig|umid|passport|card number|cvv)\b"
    r"(\s*(?:is|:|=|ko ay|ko)?\s*)(\S+)",
    re.IGNORECASE,
)


_PLACEHOLDER = re.compile(r"\[(email|link|phone|number|name|redacted)\]")


def for_matching(text: str) -> str:
    """Redact, then drop the placeholders, so identifiers never sway the FAQ match."""
    return re.sub(r"\s+", " ", _PLACEHOLDER.sub(" ", redact(text))).strip()


def redact(text: str) -> str:
    """Mask emails, URLs, phone and ID numbers, self-introduced names and secrets."""
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[link]", text)
    text = _SECRET_HINT.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    text = _PHONE.sub("[phone]", text)
    text = _LANDLINE.sub("[phone]", text)
    text = _LONG_NUMBER.sub("[number]", text)
    text = _NAME_INTRO.sub(lambda m: f"{m.group(1)} [name]", text)
    return re.sub(r"\s+", " ", text).strip()
