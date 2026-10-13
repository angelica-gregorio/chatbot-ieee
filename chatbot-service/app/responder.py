"""Turns a question into a reply: a stored answer or the fallback (FR-21, FR-22).

Decision rules, in order:

1. Greetings, thanks and goodbyes get a fixed small-talk reply.
2. If the best FAQ score clears the threshold (and the margin over the
   runner-up), the stored answer is returned word for word.
3. Otherwise the fallback is returned: a fixed message, the inquiry email for
   the most likely concern, that concern's page links, and up to two related
   FAQ questions as links. Nothing is generated, so nothing can be invented.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal
from urllib.parse import quote

from .kb import Concern, KnowledgeBase, Link
from .matcher import Scored
from .text import content_tokens, normalize

ReplyType = Literal["answer", "fallback", "smalltalk", "no_speech"]

_GREETING = re.compile(
    r"^(hi|hello|hey|good (morning|afternoon|evening)|kumusta|kamusta|magandang (umaga|hapon|gabi))\b"
)
_THANKS = re.compile(r"^(thanks|thank you|ty|salamat|maraming salamat)\b")
_BYE = re.compile(r"^(bye|goodbye|see you|paalam)\b")


@dataclass
class EmailLink:
    address: str
    subject: str
    label: str
    href: str


@dataclass
class Reply:
    type: ReplyType
    text: str
    html: str = ""
    faq_id: str | None = None
    category: str | None = None
    score: float | None = None
    links: list[Link] = field(default_factory=list)
    email: EmailLink | None = None
    suggestions: list[Link] = field(default_factory=list)
    transcript: str | None = None
    timing_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def smalltalk(message: str, kb: KnowledgeBase) -> Reply | None:
    """Fixed replies for greetings, thanks and goodbyes; only for short messages."""
    norm = normalize(message)
    if not norm or len(norm.split()) > 6:
        return None
    replies = (
        (_GREETING, kb.greeting_message),
        (_THANKS, "You're welcome! Anything else you'd like to ask?"),
        (_BYE, "Goodbye! Come back anytime."),
    )
    for pattern, text in replies:
        match = pattern.match(norm)
        # "hi, how do I volunteer?" still goes to the FAQ matcher.
        if match and not content_tokens(norm[match.end() :]):
            return Reply(type="smalltalk", text=text)
    return None


def choose_concern(message: str, kb: KnowledgeBase, ranked: list[Scored], near: float) -> Concern | None:
    """Pick the inquiry concern for a fallback reply (FR-22).

    Keyword hits decide first; failing that, the concern of a near-miss FAQ
    entry; failing that, the default concern.
    """
    tokens = set(content_tokens(message))
    norm = f" {normalize(message)} "
    best, best_hits = None, 0
    for concern in kb.concerns:
        hits = 0
        for keyword in concern.keywords:
            kw_tokens = content_tokens(keyword)
            if len(kw_tokens) > 1:
                hits += 2 if f" {normalize(keyword)} " in norm else 0
            elif kw_tokens and kw_tokens[0] in tokens:
                hits += 1
        if hits > best_hits:
            best, best_hits = concern, hits
    if best is not None:
        return best
    if ranked and ranked[0].score >= near and ranked[0].entry.concern:
        found = kb.concern(ranked[0].entry.concern)
        if found:
            return found
    return kb.concern(kb.default_concern) or (kb.concerns[0] if kb.concerns else None)


def email_link(concern: Concern) -> EmailLink:
    subject = f"Website inquiry: {concern.label}"
    return EmailLink(
        address=concern.email,
        subject=subject,
        label=f"Email {concern.label}",
        href=f"mailto:{concern.email}?subject={quote(subject)}",
    )


def decide(
    message: str,
    kb: KnowledgeBase,
    ranked: list[Scored],
    threshold: float,
    margin: float = 0.0,
    suggest_ratio: float = 0.6,
) -> Reply:
    talk = smalltalk(message, kb)
    if talk is not None:
        return talk

    best = ranked[0] if ranked else None
    runner_up = ranked[1].score if len(ranked) > 1 else 0.0
    if best and best.score >= threshold and best.score - runner_up >= margin:
        entry = best.entry
        links = list(entry.links)
        return Reply(
            type="answer",
            text=entry.answer_text,
            html=entry.answer_html,
            faq_id=entry.id,
            category=entry.category or None,
            score=round(best.score, 4),
            links=links,
        )

    near = threshold * suggest_ratio
    concern = choose_concern(message, kb, ranked, near)
    links: list[Link] = list(concern.links) if concern else []
    if kb.contact_url and all(link.url != kb.contact_url for link in links):
        links.append(Link(label="Contact page", url=kb.contact_url))
    suggestions = [
        Link(label=item.entry.question, url=item.entry.url)
        for item in ranked[:2]
        if item.score >= near and item.entry.url
    ]
    return Reply(
        type="fallback",
        text=kb.fallback_message,
        score=round(best.score, 4) if best else None,
        links=links,
        email=email_link(concern) if concern else None,
        suggestions=suggestions,
    )
