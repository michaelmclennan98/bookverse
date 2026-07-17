from __future__ import annotations

import re
from functools import lru_cache

try:
    from langdetect import DetectorFactory, LangDetectException, detect as _detect_language
except ImportError:  # Optional enhancement; the built-in heuristic remains fully usable.
    DetectorFactory = None
    LangDetectException = Exception
    _detect_language = None
else:
    DetectorFactory.seed = 0

from .models import Book, clean_text

_ENGLISH_CODES = {
    "en", "eng", "english", "en-us", "en-gb", "en-ca", "en-au", "en-nz",
}

_CODE_ALIASES = {
    "eng": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "en-ca": "en",
    "en-au": "en",
    "en-nz": "en",
    "ind": "id",
    "idn": "id",
    "spa": "es",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "ita": "it",
    "por": "pt",
    "dut": "nl",
    "nld": "nl",
}

_ENGLISH_SIGNAL_WORDS = {
    "the", "and", "of", "to", "in", "a", "is", "that", "for", "with", "as",
    "on", "by", "from", "this", "his", "her", "their", "when", "into", "after",
    "before", "about", "who", "what", "where", "why", "how", "novel", "story",
    "book", "fiction", "life", "love", "family", "friend", "friends", "young",
}

_NON_ENGLISH_SIGNAL_WORDS = {
    # Indonesian / Malay
    "dan", "yang", "dengan", "untuk", "dari", "pada", "tidak", "seorang", "memiliki",
    "sejak", "adalah", "akan", "atau", "karena", "dalam", "saat", "juga", "telah",
    # Spanish
    "el", "la", "los", "las", "una", "uno", "del", "que", "con", "para", "por",
    "como", "pero", "cuando", "donde", "esta", "este", "sus", "sobre",
    # French
    "le", "les", "des", "une", "un", "dans", "avec", "pour", "sur", "mais", "son",
    "elle", "ils", "aux", "est", "sont", "qui",
    # German
    "der", "die", "das", "und", "mit", "für", "von", "auf", "ist", "sich", "nicht",
    "ein", "eine", "den", "dem", "als",
    # Italian / Portuguese common signals
    "gli", "della", "delle", "nella", "perché", "come", "uma", "não", "com", "dos",
    "das", "pela", "seu", "sua",
}

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']+")


def normalise_language_code(value: str) -> str:
    code = clean_text(value).casefold().replace("_", "-")
    if not code:
        return ""
    return _CODE_ALIASES.get(code, code.split("-", 1)[0])


def explicit_language_status(value: str) -> str:
    """Return english, non_english or unknown from catalogue metadata."""
    raw = clean_text(value).casefold().replace("_", "-")
    if not raw:
        return "unknown"
    code = normalise_language_code(raw)
    if raw in _ENGLISH_CODES or code == "en":
        return "english"
    return "non_english"


@lru_cache(maxsize=4096)
def detect_text_language(text: str) -> str:
    cleaned = clean_text(text)
    words = _WORD_RE.findall(cleaned.casefold())
    if len(words) < 5 or sum(len(word) for word in words) < 24:
        return "unknown"

    sample = " ".join(words[:700])
    if _detect_language is not None:
        try:
            code = normalise_language_code(_detect_language(sample))
            if code:
                return "english" if code == "en" else "non_english"
        except LangDetectException:
            pass

    # Dependency-free deterministic fallback for sparse or awkward catalogue copy.
    english_hits = sum(word in _ENGLISH_SIGNAL_WORDS for word in words)
    foreign_hits = sum(word in _NON_ENGLISH_SIGNAL_WORDS for word in words)
    if foreign_hits >= 3 and foreign_hits > english_hits:
        return "non_english"
    if english_hits >= 3 and english_hits >= foreign_hits:
        return "english"
    return "unknown"


def book_language_status(book: Book) -> str:
    """Classify the readable catalogue record, not merely the edition code.

    Catalogue language metadata wins when present. If it is absent or malformed,
    the synopsis, title and subjects are inspected. This prevents a non-English
    description from reaching an English-only recommendation dialog even when the
    provider forgot to label the language.
    """
    explicit = explicit_language_status(book.language)
    description_status = detect_text_language(book.description)

    # A clearly non-English synopsis overrides unreliable provider language labels.
    # Some Open Library editions are tagged English even when the supplied synopsis
    # is Indonesian, Spanish or another language.
    if description_status == "non_english":
        return "non_english"
    if explicit != "unknown":
        return explicit
    if description_status == "english":
        return "english"

    combined = " ".join(
        part for part in (book.display_title, book.category_text) if clean_text(part)
    )
    return detect_text_language(combined)


def is_english_book(book: Book, *, allow_unknown: bool = True) -> bool:
    status = book_language_status(book)
    return status == "english" or (allow_unknown and status == "unknown")
