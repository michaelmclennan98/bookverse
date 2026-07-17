from __future__ import annotations

import re
from dataclasses import dataclass, field

GENRES = (
    "fantasy", "romance", "dark romance", "science fiction", "sci-fi", "horror",
    "thriller", "crime", "mystery", "historical fiction", "young adult", "ya",
    "paranormal", "urban fantasy", "cozy mystery", "dystopian", "literary fiction",
    "non-fiction", "biography", "memoir", "history", "self-help", "adventure",
    "comedy", "graphic novel", "manga", "poetry", "classic", "children's",
)

TROPES = (
    "enemies to lovers", "friends to lovers", "slow burn", "fake dating",
    "forced proximity", "found family", "chosen one", "second chance", "time travel",
    "magic school", "academy", "dragons", "vampires", "witches", "pirates",
    "apocalypse", "political intrigue", "morally grey", "cozy", "dark academia",
)

FILLER = {
    "i", "want", "a", "an", "the", "book", "books", "please", "recommend", "me",
    "give", "find", "something", "with", "that", "has", "and", "but", "really",
    "read", "novel", "story", "about", "for", "to", "of", "some", "any",
}


@dataclass(slots=True)
class SmartSearchPlan:
    original: str
    api_query: str
    genres: list[str] = field(default_factory=list)
    tropes: list[str] = field(default_factory=list)
    author: str = ""
    similar_to: str = ""
    min_pages: int | None = None
    max_pages: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    negative_terms: list[str] = field(default_factory=list)

    @property
    def explanation(self) -> str:
        parts: list[str] = []
        if self.similar_to:
            parts.append(f"similar to {self.similar_to}")
        if self.genres:
            parts.append("genres: " + ", ".join(self.genres))
        if self.tropes:
            parts.append("themes/tropes: " + ", ".join(self.tropes))
        if self.author:
            parts.append(f"author: {self.author}")
        if self.min_pages is not None:
            parts.append(f"at least {self.min_pages} pages")
        if self.max_pages is not None:
            parts.append(f"at most {self.max_pages} pages")
        if self.year_from is not None:
            parts.append(f"published from {self.year_from}")
        if self.year_to is not None:
            parts.append(f"published by {self.year_to}")
        if self.negative_terms:
            parts.append("avoid: " + ", ".join(self.negative_terms))
        return "; ".join(parts) if parts else "general keyword search"


def parse_smart_query(text: str) -> SmartSearchPlan:
    original = " ".join(text.strip().split())
    lowered = original.casefold()

    genres = [genre for genre in GENRES if _phrase_present(lowered, genre)]
    tropes = [trope for trope in TROPES if _phrase_present(lowered, trope)]

    author = ""
    author_match = re.search(
        r"\b(?:by|author(?: is|:)?)\s+([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})",
        original,
    )
    if author_match:
        author = author_match.group(1).strip(" .,;:")

    similar_to = ""
    similar_match = re.search(
        r"\b(?:like|similar to)\s+(.+?)(?=\s+(?:but|with|under|over|without|and)\b|$)",
        original,
        flags=re.IGNORECASE,
    )
    if similar_match:
        similar_to = similar_match.group(1).strip(" .,;:")

    max_pages = _extract_number(lowered, r"(?:under|less than|max(?:imum)?(?: of)?)\s+(\d{2,4})\s*pages?")
    min_pages = _extract_number(lowered, r"(?:over|more than|min(?:imum)?(?: of)?|at least)\s+(\d{2,4})\s*pages?")
    year_from = _extract_number(lowered, r"(?:after|since|from)\s+(19\d{2}|20\d{2})")
    year_to = _extract_number(lowered, r"(?:before|by)\s+(19\d{2}|20\d{2})")

    negative_terms: list[str] = []
    for match in re.finditer(r"\b(?:no|not|without|avoid)\s+([a-z][a-z -]{1,30})(?=,|\.|;|\b(?:but|and|with|under|over)\b|$)", lowered):
        term = match.group(1).strip()
        if term:
            negative_terms.append(term)
    if "little romance" in lowered:
        negative_terms.append("heavy romance")

    preferred_terms = [*genres, *tropes]
    if similar_to:
        preferred_terms.insert(0, similar_to)
    if author:
        preferred_terms.append(author)

    if not preferred_terms:
        tokens = re.findall(r"[a-zA-Z0-9'-]+", original)
        preferred_terms = [token for token in tokens if token.casefold() not in FILLER][:12]

    api_query = " ".join(dict.fromkeys(preferred_terms)).strip() or original
    return SmartSearchPlan(
        original=original,
        api_query=api_query,
        genres=genres,
        tropes=tropes,
        author=author,
        similar_to=similar_to,
        min_pages=min_pages,
        max_pages=max_pages,
        year_from=year_from,
        year_to=year_to,
        negative_terms=list(dict.fromkeys(negative_terms)),
    )


def _phrase_present(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _extract_number(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None
