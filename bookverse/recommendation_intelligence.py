from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable

from .language_utils import is_english_book
from .models import Book
from .recommender import BookProfile, profile_book

RULES_SETTING_KEY = "recommendation_rules_v21"

DEFAULT_RULES: dict[str, Any] = {
    "english_only": True,
    "adult_only": False,
    "require_description": True,
    "minimum_public_rating": 0.0,
    "minimum_rating_count": 0,
    "minimum_pages": 0,
    "maximum_pages": 0,
    "published_from": 0,
    "published_to": 0,
    "standalone_only": False,
    "exclude_textbooks": True,
    "exclude_reference": True,
    "exclude_poetry": False,
    "exclude_graphic_novels": False,
    "exclude_childrens": True,
    "exclude_religion": False,
    "exclude_nonfiction": False,
    "diversity": 45,
    "maximum_per_author": 2,
    "maximum_per_primary_genre": 5,
}


def normalise_rules(payload: dict[str, Any] | str | None) -> dict[str, Any]:
    rules = dict(DEFAULT_RULES)
    if isinstance(payload, str) and payload.strip():
        try:
            loaded = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            loaded = {}
    elif isinstance(payload, dict):
        loaded = payload
    else:
        loaded = {}

    for key in rules:
        if key in loaded:
            rules[key] = loaded[key]

    for key in (
        "english_only", "adult_only", "require_description", "standalone_only",
        "exclude_textbooks", "exclude_reference", "exclude_poetry",
        "exclude_graphic_novels", "exclude_childrens", "exclude_religion",
        "exclude_nonfiction",
    ):
        rules[key] = bool(rules.get(key))

    rules["minimum_public_rating"] = max(0.0, min(float(rules.get("minimum_public_rating") or 0.0), 5.0))
    rules["minimum_rating_count"] = max(0, int(rules.get("minimum_rating_count") or 0))
    rules["minimum_pages"] = max(0, int(rules.get("minimum_pages") or 0))
    rules["maximum_pages"] = max(0, int(rules.get("maximum_pages") or 0))
    rules["published_from"] = max(0, int(rules.get("published_from") or 0))
    rules["published_to"] = max(0, int(rules.get("published_to") or 0))
    rules["diversity"] = max(0, min(int(rules.get("diversity") or 0), 100))
    rules["maximum_per_author"] = max(1, min(int(rules.get("maximum_per_author", 2)), 10))
    rules["maximum_per_primary_genre"] = max(1, min(int(rules.get("maximum_per_primary_genre", 5)), 20))
    return rules


def _book_corpus(book: Book) -> str:
    return " ".join(
        [book.title, book.subtitle, book.description, book.publisher, *book.categories]
    ).casefold()


def _series_status(book: Book) -> str:
    text = _book_corpus(book)
    if re.search(r"\b(?:book|volume|vol\.?|part)\s*(?:#\s*)?[2-9]\d*\b", text):
        return "later_series"
    if re.search(r"\b(?:book|volume|vol\.?|part)\s*(?:#\s*)?1\b", text):
        return "series_start"
    if any(term in text for term in ("book one", "first in the series", "series book", "trilogy")):
        return "series_start"
    if "series" in text:
        return "series"
    return "unknown"


def _primary(values: Iterable[str], fallback: str = "Unknown") -> str:
    cleaned = [str(value).replace("_", " ").title() for value in values if value]
    return cleaned[0] if cleaned else fallback


def book_dna(book: Book) -> dict[str, Any]:
    profile: BookProfile = profile_book(book)
    corpus = _book_corpus(book)

    romance = "None"
    if "romance" in profile.genres or "erotica" in profile.genres:
        romance = "High" if any(term in corpus for term in ("erotic", "steamy", "spicy", "explicit")) else "Medium"
    elif any(term in corpus for term in ("love interest", "romantic subplot", "romance")):
        romance = "Low"

    intensity = "Moderate"
    if profile.content_level == "extreme" or "extreme_horror" in profile.subgenres:
        intensity = "Extreme"
    elif profile.content_level == "mature" or "violent" in profile.tones or "dark" in profile.tones:
        intensity = "Dark"
    elif any(term in profile.tones for term in ("cozy", "hopeful", "humorous")):
        intensity = "Light"

    pace = "Balanced"
    if "fast_paced" in profile.tones or "suspenseful" in profile.tones:
        pace = "Fast"
    elif "slow_burn" in profile.tones or "introspective" in profile.tones:
        pace = "Slow burn"

    return {
        "primary_genre": _primary(sorted(profile.genres)),
        "subgenres": [value.replace("_", " ").title() for value in sorted(profile.subgenres)[:4]],
        "themes": [value.replace("_", " ").title() for value in sorted(profile.themes)[:5]],
        "tones": [value.replace("_", " ").title() for value in sorted(profile.tones)[:4]],
        "audience": _primary(sorted(profile.target_audiences)),
        "work_type": profile.primary_work_type.replace("_", " ").title(),
        "content_level": profile.content_level.title(),
        "romance": romance,
        "intensity": intensity,
        "pace": pace,
        "series": _series_status(book).replace("_", " ").title(),
        "pages": int(book.page_count or 0),
        "year": int(book.published_year or 0),
    }


def rule_rejections(book: Book, payload: dict[str, Any] | str | None) -> list[str]:
    rules = normalise_rules(payload)
    profile = profile_book(book)
    text = _book_corpus(book)
    reasons: list[str] = []

    if rules["english_only"] and not is_english_book(book, allow_unknown=False):
        reasons.append("not confirmed as English")
    if rules["adult_only"] and profile.primary_audience in {"children", "middle_grade", "young_adult"}:
        reasons.append("outside the adult audience rule")
    if rules["require_description"] and len(book.description.strip()) < 20:
        reasons.append("missing a useful description")
    if rules["minimum_public_rating"] > 0 and (
        book.average_rating is None or float(book.average_rating) < rules["minimum_public_rating"]
    ):
        reasons.append("below the minimum public rating")
    if rules["minimum_rating_count"] > 0 and int(book.ratings_count or 0) < rules["minimum_rating_count"]:
        reasons.append("too few public ratings")
    if rules["minimum_pages"] > 0 and book.page_count and int(book.page_count) < rules["minimum_pages"]:
        reasons.append("shorter than the minimum length")
    if rules["maximum_pages"] > 0 and book.page_count and int(book.page_count) > rules["maximum_pages"]:
        reasons.append("longer than the maximum length")
    if rules["published_from"] > 0 and book.published_year and int(book.published_year) < rules["published_from"]:
        reasons.append("older than the publication rule")
    if rules["published_to"] > 0 and book.published_year and int(book.published_year) > rules["published_to"]:
        reasons.append("newer than the publication rule")
    if rules["standalone_only"] and _series_status(book) in {"series", "series_start", "later_series"}:
        reasons.append("appears to be part of a series")

    textbook_markers = (
        "textbook", "workbook", "coursebook", "student edition", "teacher edition",
        "study guide", "study aids", "curriculum", "teaching resource",
        "problems, exercises", "composition and exercises", "grammar and composition",
        "literary criticism", "criticism and interpretation",
    )
    reference_markers = (
        "reference work", "handbook", "manual", "encyclopedia", "dictionary of",
        "instructional guide", "how-to guide", "guidebook",
    )
    if rules["exclude_textbooks"] and (
        profile.primary_work_type in {"textbook", "academic_criticism"}
        or any(marker in text for marker in textbook_markers)
    ):
        reasons.append("textbook or academic work")
    if rules["exclude_reference"] and (
        profile.primary_work_type in {"reference", "manual", "guidebook", "cookbook"}
        or any(marker in text for marker in reference_markers)
    ):
        reasons.append("reference or instructional work")
    if rules["exclude_poetry"] and profile.primary_work_type == "poetry":
        reasons.append("poetry excluded")
    if rules["exclude_graphic_novels"] and profile.primary_work_type == "graphic_novel":
        reasons.append("graphic novels excluded")
    if rules["exclude_childrens"] and (
        profile.primary_audience in {"children", "middle_grade"} or profile.primary_work_type == "picture_book"
    ):
        reasons.append("children's book excluded")
    if rules["exclude_religion"] and (
        "religion" in profile.genres
        or any(term in text for term in ("christianity", "bible study", "devotional", "theology", "religious studies"))
    ):
        reasons.append("religious book excluded")
    if rules["exclude_nonfiction"] and profile.fiction_status == "nonfiction":
        reasons.append("nonfiction excluded")

    return reasons



def filter_recommendation_payloads(
    payloads: Iterable[dict[str, Any]],
    rules_payload: dict[str, Any] | str | None,
) -> tuple[list[dict[str, Any]], int]:
    """Return only saved recommendations that still satisfy the active rules.

    Saved recommendation sets can outlive a deployment or a later rule change.
    Filtering them at display time prevents an older result with no description,
    the wrong language or an excluded work type from remaining visible merely
    because a replacement scan was temporarily unavailable.
    """
    allowed: list[dict[str, Any]] = []
    hidden = 0
    seen: set[str] = set()

    for payload in payloads:
        try:
            book = Book.from_dict(payload.get("book") or payload)
        except (TypeError, ValueError, KeyError):
            hidden += 1
            continue

        if book.uid in seen:
            hidden += 1
            continue
        seen.add(book.uid)

        if rule_rejections(book, rules_payload):
            hidden += 1
            continue

        allowed.append(dict(payload))

    return allowed, hidden


def recommendation_evidence_strength(seed: Book, candidate: Book) -> int:
    """Count meaningful Book DNA overlaps while ignoring broad catalogue labels."""
    seed_profile = profile_book(seed)
    candidate_profile = profile_book(candidate)

    generic_genres = {
        "fiction", "nonfiction", "literature", "general", "history",
        "novel", "stories", "adult",
    }
    genre_overlap = (seed_profile.genres & candidate_profile.genres) - generic_genres
    subgenre_overlap = seed_profile.subgenres & candidate_profile.subgenres
    theme_overlap = seed_profile.themes & candidate_profile.themes
    tone_overlap = seed_profile.tones & candidate_profile.tones

    strength = 0
    strength += min(3, len(subgenre_overlap)) * 3
    strength += min(3, len(genre_overlap)) * 2
    strength += min(3, len(theme_overlap)) * 2
    strength += min(2, len(tone_overlap))

    if (
        seed_profile.primary_work_type == candidate_profile.primary_work_type
        and seed_profile.primary_work_type not in {"unknown", "general_fiction"}
    ):
        strength += 1

    return strength

def feedback_adjustment(book: Book, feedback_values: set[str]) -> tuple[float, list[str]]:
    dna = book_dna(book)
    multiplier = 1.0
    notes: list[str] = []

    if "Less romance" in feedback_values and dna["romance"] in {"Medium", "High"}:
        multiplier -= 0.22
        notes.append("romance preference penalty")
    if "Too much romance" in feedback_values and dna["romance"] != "None":
        multiplier -= 0.30
        notes.append("strong romance penalty")
    if "More intense" in feedback_values or "Not dark enough" in feedback_values:
        if dna["intensity"] in {"Dark", "Extreme"}:
            multiplier += 0.18
            notes.append("intensity preference boost")
        else:
            multiplier -= 0.08
    if "Lighter read" in feedback_values or "Too extreme" in feedback_values:
        if dna["intensity"] == "Light":
            multiplier += 0.18
            notes.append("lighter-read preference boost")
        elif dna["intensity"] in {"Dark", "Extreme"}:
            multiplier -= 0.18
    if "Too long" in feedback_values and book.page_count and int(book.page_count) > 450:
        multiplier -= 0.16
        notes.append("length preference penalty")
    if "Too short" in feedback_values and book.page_count and int(book.page_count) < 220:
        multiplier -= 0.14
        notes.append("short-book preference penalty")
    if "Too old" in feedback_values and book.published_year and int(book.published_year) < 2000:
        multiplier -= 0.12
        notes.append("publication-age penalty")
    if "Wrong genre" in feedback_values:
        multiplier -= 0.04

    return max(0.35, multiplier), notes


def score_breakdown(record: dict[str, Any]) -> dict[str, float]:
    book: Book = record["book"] if isinstance(record.get("book"), Book) else Book.from_dict(record.get("book") or {})
    best_percent = max(0, min(int(record.get("best_percent") or record.get("match_percent") or 0), 100))
    seed_count = max(0, int(record.get("seed_count") or 0))
    public_rating = float(book.average_rating or 0.0)
    ratings_count = int(book.ratings_count or 0)

    match = round(best_percent * 0.52, 1)
    cross_seed = round(min(seed_count, 4) / 4 * 16.0, 1)
    metadata = 4.0
    if len(book.description) >= 180:
        metadata += 4.0
    if book.categories:
        metadata += 2.0
    public_quality = 0.0
    if public_rating:
        public_quality += max(0.0, min((public_rating - 3.0) * 3.0, 6.0))
    if ratings_count:
        public_quality += min(math.log10(max(ratings_count, 1)) * 1.4, 4.0)
    preference = round(float(record.get("preference_points") or 0.0), 1)

    return {
        "Taste match": round(match, 1),
        "Cross-book evidence": round(cross_seed, 1),
        "Metadata confidence": round(metadata, 1),
        "Public quality": round(public_quality, 1),
        "Preference learning": round(preference, 1),
    }


def final_match_percent(record: dict[str, Any]) -> int:
    breakdown = score_breakdown(record)
    total = sum(breakdown.values())
    return max(1, min(99, int(round(total))))


def _profile_overlap(left: Book, right: Book) -> float:
    left_profile = profile_book(left)
    right_profile = profile_book(right)
    left_signals = left_profile.genres | left_profile.subgenres | left_profile.themes | left_profile.tones
    right_signals = right_profile.genres | right_profile.subgenres | right_profile.themes | right_profile.tones
    if not left_signals or not right_signals:
        return 0.0
    return len(left_signals & right_signals) / max(1, len(left_signals | right_signals))


def select_diverse_records(
    records: list[dict[str, Any]],
    limit: int,
    payload: dict[str, Any] | str | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rules = normalise_rules(payload)
    diversity = rules["diversity"] / 100.0
    author_cap = int(rules["maximum_per_author"])
    genre_cap = int(rules["maximum_per_primary_genre"])
    remaining = list(records)
    selected: list[dict[str, Any]] = []
    author_counts: dict[str, int] = {}
    genre_counts: dict[str, int] = {}
    skipped_author = 0
    skipped_genre = 0

    while remaining and len(selected) < max(1, int(limit)):
        best_index = -1
        best_adjusted = float("-inf")
        for index, record in enumerate(remaining):
            book: Book = record["book"]
            author = book.author_text.casefold().strip() or book.uid
            genre = str(book_dna(book)["primary_genre"]).casefold()
            if author_counts.get(author, 0) >= author_cap:
                continue
            if genre_counts.get(genre, 0) >= genre_cap:
                continue

            base = float(record.get("rank_score") or record.get("score") or 0.0)
            overlap = max((_profile_overlap(book, item["book"]) for item in selected), default=0.0)
            adjusted = base - (overlap * diversity * max(base, 1.0) * 0.62)
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index

        if best_index < 0:
            for record in remaining:
                book = record["book"]
                author = book.author_text.casefold().strip() or book.uid
                genre = str(book_dna(book)["primary_genre"]).casefold()
                if author_counts.get(author, 0) >= author_cap:
                    skipped_author += 1
                elif genre_counts.get(genre, 0) >= genre_cap:
                    skipped_genre += 1
            break

        chosen = remaining.pop(best_index)
        book = chosen["book"]
        author = book.author_text.casefold().strip() or book.uid
        genre = str(book_dna(book)["primary_genre"]).casefold()
        author_counts[author] = author_counts.get(author, 0) + 1
        genre_counts[genre] = genre_counts.get(genre, 0) + 1
        selected.append(chosen)

    return selected, {
        "diversity_author_skips": skipped_author,
        "diversity_genre_skips": skipped_genre,
    }


def rules_summary(payload: dict[str, Any] | str | None) -> list[str]:
    rules = normalise_rules(payload)
    labels: list[str] = []
    if rules["english_only"]:
        labels.append("English only")
    if rules["adult_only"]:
        labels.append("Adults only")
    if rules["require_description"]:
        labels.append("Description required")
    if rules["minimum_public_rating"]:
        labels.append(f"{rules['minimum_public_rating']:.1f}★ minimum")
    if rules["minimum_rating_count"]:
        labels.append(f"{rules['minimum_rating_count']}+ ratings")
    if rules["minimum_pages"] or rules["maximum_pages"]:
        labels.append(f"{rules['minimum_pages'] or 'any'}–{rules['maximum_pages'] or 'any'} pages")
    if rules["standalone_only"]:
        labels.append("Standalone only")
    labels.append(f"Diversity {rules['diversity']}%")
    return labels
