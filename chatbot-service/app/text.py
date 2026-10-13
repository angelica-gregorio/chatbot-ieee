"""Text normalisation shared by the lexical matcher and the concern router."""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^a-z0-9]+")

# English function words plus common Filipino particles seen in Taglish questions.
STOPWORDS = frozenset(
    """
    a an the and or but if of to in on at by for with from about as into over
    is are was were be been being am do does did doing done have has had having
    i me my mine we us our you your he she it its they them their this that these
    those there here what which who whom whose when where why how can could would
    should will shall may might must just so than too very also any some all
    please hi hello hey thanks thank pls po ba ang ng mga sa si ni ko ako ka mo
    namin natin kayo kami tayo na pa lang din rin ito iyan yan yung un paano ano
    saan kailan sino bakit pwede puwede gusto
    """.split()
)

# Small, documented synonym map for the lexical baseline. The embedding matcher
# does not need it. Keys and values are already-normalised single tokens.
SYNONYMS = {
    "signup": "register",
    "sign": "register",
    "enrol": "register",
    "enroll": "register",
    "registration": "register",
    "apply": "register",
    "application": "register",
    "join": "member",
    "membership": "member",
    "fee": "cost",
    "fees": "cost",
    "price": "cost",
    "pay": "cost",
    "payment": "cost",
    "email": "contact",
    "reach": "contact",
    "volunteering": "volunteer",
    "volunteers": "volunteer",
    "webinar": "event",
    "seminar": "event",
    "workshop": "event",
    "talk": "event",
}


def normalize(text: str) -> str:
    """Lower-case, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("sign-up", "signup").replace("sign up", "signup")
    return _NON_WORD.sub(" ", text).strip()


def stem(word: str) -> str:
    """A deliberately light suffix stripper; character n-grams cover the rest."""
    if len(word) <= 3 or word.isdigit():
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            if len(base) > 3 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            return base
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def content_tokens(text: str) -> list[str]:
    """Normalised, synonym-mapped, stemmed tokens with stopwords removed."""
    out: list[str] = []
    for token in normalize(text).split():
        if token in STOPWORDS:
            continue
        token = SYNONYMS.get(token, token)
        out.append(stem(token))
    return out


def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Character n-grams over each normalised word, padded with spaces."""
    grams: list[str] = []
    for token in normalize(text).split():
        if token in STOPWORDS:
            continue
        padded = f" {token} "
        if len(padded) <= n:
            grams.append(padded)
            continue
        grams.extend(padded[i : i + n] for i in range(len(padded) - n + 1))
    return grams
