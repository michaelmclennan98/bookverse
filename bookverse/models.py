from __future__ import annotations

import ast
import html
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item) for item in value if item not in (None, ""))
    elif isinstance(value, dict):
        value = value.get("value") or value.get("text") or ""
    text = str(value).strip()
    # Some catalogue fields arrive as a stringified Python/JSON-style list, for
    # example "['Me está viendo']". Parse those instead of showing brackets.
    if len(text) >= 2 and text[0] in "[(" and text[-1] in ")]":
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple, set)):
                text = " ".join(str(item) for item in parsed if item not in (None, ""))
        except (ValueError, SyntaxError):
            pass
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def unique_strings(values: Iterable[Any], limit: int | None = None) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
            if limit and len(output) >= limit:
                break
    return tuple(output)


def secure_url(value: str) -> str:
    return value.replace("http://", "https://", 1) if value.startswith("http://") else value


@dataclass(slots=True)
class Book:
    source: str
    source_id: str
    title: str
    subtitle: str = ""
    authors: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    categories: tuple[str, ...] = field(default_factory=tuple)
    publisher: str = ""
    published_date: str = ""
    page_count: int | None = None
    language: str = ""
    isbn10: str = ""
    isbn13: str = ""
    average_rating: float | None = None
    ratings_count: int = 0
    thumbnail: str = ""
    cover_url: str = ""
    preview_link: str = ""
    info_link: str = ""
    buy_link: str = ""
    is_ebook: bool = False
    ebook_available: bool = False
    public_domain: bool = False

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def author_text(self) -> str:
        return ", ".join(self.authors) if self.authors else "Unknown author"

    @property
    def category_text(self) -> str:
        return ", ".join(self.categories)

    @property
    def display_title(self) -> str:
        return f"{self.title}: {self.subtitle}" if self.subtitle else self.title

    @property
    def published_year(self) -> int | None:
        match = re.search(r"\b(1[0-9]{3}|20[0-9]{2}|2100)\b", self.published_date)
        return int(match.group(1)) if match else None

    @property
    def primary_isbn(self) -> str:
        return self.isbn13 or self.isbn10

    @property
    def best_cover(self) -> str:
        return self.cover_url or self.thumbnail

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["authors"] = list(self.authors)
        payload["categories"] = list(self.categories)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Book":
        data = dict(payload)
        data["authors"] = tuple(data.get("authors") or ())
        data["categories"] = tuple(data.get("categories") or ())
        return cls(**data)

    @classmethod
    def from_google(cls, item: dict[str, Any]) -> "Book":
        info = item.get("volumeInfo") or {}
        access = item.get("accessInfo") or {}
        sale = item.get("saleInfo") or {}
        identifiers = {
            entry.get("type"): entry.get("identifier", "")
            for entry in info.get("industryIdentifiers", [])
            if isinstance(entry, dict)
        }
        images = info.get("imageLinks") or {}
        cover = next(
            (
                images.get(name)
                for name in ("extraLarge", "large", "medium", "small", "thumbnail")
                if images.get(name)
            ),
            "",
        )
        thumbnail = images.get("thumbnail") or images.get("smallThumbnail") or cover
        retail = sale.get("retailPrice") or sale.get("listPrice") or {}
        return cls(
            source="google",
            source_id=str(item.get("id") or identifiers.get("ISBN_13") or info.get("title") or "unknown"),
            title=clean_text(info.get("title")) or "Untitled",
            subtitle=clean_text(info.get("subtitle")),
            authors=unique_strings(info.get("authors") or []),
            description=clean_text(info.get("description")),
            categories=unique_strings(info.get("categories") or ([info.get("mainCategory")] if info.get("mainCategory") else []), 12),
            publisher=clean_text(info.get("publisher")),
            published_date=clean_text(info.get("publishedDate")),
            page_count=_safe_int(info.get("pageCount")),
            language=clean_text(info.get("language")),
            isbn10=clean_text(identifiers.get("ISBN_10")),
            isbn13=clean_text(identifiers.get("ISBN_13")),
            average_rating=_safe_float(info.get("averageRating")),
            ratings_count=_safe_int(info.get("ratingsCount")) or 0,
            thumbnail=secure_url(clean_text(thumbnail)),
            cover_url=secure_url(clean_text(cover)),
            preview_link=secure_url(clean_text(info.get("previewLink"))),
            info_link=secure_url(clean_text(info.get("canonicalVolumeLink") or info.get("infoLink"))),
            buy_link=secure_url(clean_text(sale.get("buyLink"))),
            is_ebook=bool(sale.get("isEbook")),
            ebook_available=bool((access.get("epub") or {}).get("isAvailable") or (access.get("pdf") or {}).get("isAvailable")),
            public_domain=bool(access.get("publicDomain")),
        )

    @classmethod
    def from_openlibrary(cls, doc: dict[str, Any]) -> "Book":
        work_key = clean_text(doc.get("key"))
        source_id = work_key.rsplit("/", 1)[-1] if work_key else clean_text(doc.get("cover_edition_key"))
        isbns = [clean_text(value) for value in doc.get("isbn") or []]
        isbn13 = next((value for value in isbns if len(re.sub(r"\D", "", value)) == 13), "")
        isbn10 = next((value for value in isbns if len(re.sub(r"\D", "", value)) == 10), "")
        cover_id = _safe_int(doc.get("cover_i"))
        cover_edition = clean_text(doc.get("cover_edition_key"))
        if cover_id and cover_id > 0:
            cover = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
            thumbnail = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
        elif cover_edition:
            cover = f"https://covers.openlibrary.org/b/olid/{cover_edition}-L.jpg"
            thumbnail = f"https://covers.openlibrary.org/b/olid/{cover_edition}-M.jpg"
        elif isbn13 or isbn10:
            cover_isbn = isbn13 or isbn10
            cover = f"https://covers.openlibrary.org/b/isbn/{cover_isbn}-L.jpg"
            thumbnail = f"https://covers.openlibrary.org/b/isbn/{cover_isbn}-M.jpg"
        else:
            cover = thumbnail = ""
        info_link = f"https://openlibrary.org{work_key}" if work_key else ""
        languages = doc.get("language") or []
        ebook_access = clean_text(doc.get("ebook_access"))
        return cls(
            source="openlibrary",
            source_id=source_id or isbn13 or isbn10 or clean_text(doc.get("title")) or "unknown",
            title=clean_text(doc.get("title")) or "Untitled",
            subtitle=clean_text(doc.get("subtitle")),
            authors=unique_strings(doc.get("author_name") or []),
            description=clean_text(doc.get("first_sentence") or ""),
            categories=unique_strings(doc.get("subject") or [], 12),
            publisher=next(iter(unique_strings(doc.get("publisher") or [], 1)), ""),
            published_date=str(_best_openlibrary_year(doc) or ""),
            page_count=_safe_int(doc.get("number_of_pages_median")),
            language=clean_text(languages[0] if languages else ""),
            isbn10=isbn10,
            isbn13=isbn13,
            average_rating=_safe_float(doc.get("ratings_average")),
            ratings_count=_safe_int(doc.get("ratings_count")) or 0,
            thumbnail=thumbnail,
            cover_url=cover,
            preview_link=info_link,
            info_link=info_link,
            is_ebook=ebook_access not in {"", "no_ebook"},
            ebook_available=ebook_access in {"borrowable", "public"},
            public_domain=ebook_access == "public",
        )


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _best_openlibrary_year(doc: dict[str, Any]) -> int | None:
    """Prefer the most common edition year over occasionally corrupt first_publish_year."""
    years: list[int] = []
    for value in doc.get("publish_year") or []:
        year = _safe_int(value)
        if year and 1450 <= year <= 2100:
            years.append(year)
    if years:
        from collections import Counter
        counts = Counter(years)
        return sorted(counts, key=lambda y: (counts[y], y), reverse=True)[0]
    year = _safe_int(doc.get("first_publish_year"))
    return year if year and 1450 <= year <= 2100 else None
