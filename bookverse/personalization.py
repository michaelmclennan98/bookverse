from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from .models import Book, unique_strings

GENERIC_CATEGORIES = {
    "fiction", "nonfiction", "literature", "books", "general", "juvenile fiction",
    "young adult fiction", "american literature", "english literature",
    "new york times bestseller", "new york times reviewed", "bestsellers",
    "award winners", "awards", "reading level", "school reading",
}

NOISY_CATEGORY_FRAGMENTS = (
    "new york times", "bestseller", "award", "reading level", "grade ",
    "open library", "accessible book", "protected daisy", "large type",
    "internet archive", "translations", "bibliography", "catalog",
)


def _meaningful_category(value: str) -> bool:
    cleaned = " ".join(str(value or "").split()).strip()
    folded = cleaned.casefold()
    if not cleaned or folded in GENERIC_CATEGORIES:
        return False
    if any(fragment in folded for fragment in NOISY_CATEGORY_FRAGMENTS):
        return False
    return 2 <= len(cleaned) <= 60


def taste_fingerprint(profile: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    payload = {
        "profile": {
            "id": profile.get("id"),
            "updated_at": profile.get("updated_at"),
            "favourite_niches": profile.get("favourite_niches") or [],
            "top_books": profile.get("top_books") or [],
        },
        "entries": [
            {
                "uid": entry["uid"],
                "shelf": entry["shelf"],
                "rating": entry["user_rating"],
                "updated_at": entry["updated_at"],
            }
            for entry in entries
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def build_taste_seed(profile: dict[str, Any], entries: list[dict[str, Any]]) -> Book:
    """Build a synthetic book record representing one user's reading taste."""
    category_weights: Counter[str] = Counter()
    descriptions: list[str] = []
    liked_titles: list[str] = []

    for niche in profile.get("favourite_niches") or []:
        category_weights[str(niche)] += 6

    for entry in entries:
        book: Book = entry["book"]
        shelf = entry.get("shelf") or ""
        rating = float(entry.get("user_rating") or 0.0)
        weight = 1
        if shelf == "Favourites":
            weight += 5
        elif shelf == "Finished":
            weight += 2
        elif shelf == "DNF":
            weight = -4
        if rating >= 4.5:
            weight += 5
        elif rating >= 4.0:
            weight += 3
        elif rating and rating <= 2.0:
            weight -= 4

        for category in book.categories:
            cleaned = " ".join(category.split()).strip()
            if _meaningful_category(cleaned):
                category_weights[cleaned] += weight

        if weight >= 3:
            liked_titles.append(book.display_title)
            if book.description:
                descriptions.append(book.description[:900])

    top_categories = [
        category
        for category, score in category_weights.most_common(28)
        if score > 0
    ]
    top_books = [str(value) for value in profile.get("top_books") or []]
    narrative_parts = []
    if top_books:
        narrative_parts.append("Favourite books: " + "; ".join(top_books[:12]))
    if liked_titles:
        narrative_parts.append("Books this reader liked: " + "; ".join(liked_titles[:12]))
    narrative_parts.extend(descriptions[:6])

    source_id = taste_fingerprint(profile, entries)
    return Book(
        source="bookverse",
        source_id=f"taste-{source_id}",
        title="Personalised BookVerse taste profile",
        authors=(),
        description=" ".join(narrative_parts)[:5000],
        categories=unique_strings(top_categories, 28),
        language="en",
    )


def taste_summary(profile: dict[str, Any], entries: list[dict[str, Any]], limit: int = 8) -> list[str]:
    seed = build_taste_seed(profile, entries)
    return list(seed.categories[:limit])
