from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import streamlit as st

from .api_clients import BookSearchService, merge_book_records
from .models import Book
from .persistent_cache import get_cached, set_cached
from .recommender import rank_similar_detailed, rank_smart_results
from .smart_search import parse_smart_query

SEARCH_TTL = 60 * 60 * 24 * 7
DETAIL_TTL = 60 * 60 * 24 * 30
RECOMMENDATION_TTL = 60 * 60 * 24 * 7


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _identity(book: Book) -> str:
    return f"{_normalise(book.title)}|{_normalise(book.author_text)}"


@st.cache_data(ttl=60 * 10, show_spinner=False, max_entries=500)
def cached_search(
    query: str,
    mode: str,
    provider: str,
    max_results: int,
    language: str,
    order_by: str,
    ebook_filter: str,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    page_index: int = 0,
    database_path: str = "",
) -> tuple[list[dict], list[str]]:
    parts = (
        query, mode, provider, max_results, language, order_by,
        ebook_filter, bool(google_api_key), page_index, "search-v2",
    )
    cached = get_cached(database_path, "search", *parts)
    if isinstance(cached, dict):
        return list(cached.get("books") or []), list(cached.get("messages") or [])

    service = BookSearchService(google_api_key, open_library_contact, timeout)
    response = service.search(
        query=query,
        mode=mode,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        max_results=max_results,
        language=language,
        order_by=order_by,
        ebook_filter=ebook_filter,
        page_index=page_index,
    )
    result = ([book.to_dict() for book in response.books], response.provider_messages)
    set_cached(
        database_path,
        "search",
        parts,
        {"books": result[0], "messages": result[1]},
        SEARCH_TTL,
    )
    return result


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False, max_entries=700)
def cached_enrich_catalogue_book(
    book_payload: dict,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    engine_version: str = "v20-catalogue-details",
    database_path: str = "",
) -> dict:
    seed = Book.from_dict(book_payload)
    parts = (seed.uid, seed.primary_isbn, engine_version, bool(google_api_key))
    cached = get_cached(database_path, "book-detail", *parts)
    if isinstance(cached, dict) and cached.get("title"):
        return cached

    service = BookSearchService(google_api_key, open_library_contact, timeout)
    book = seed  # compatibility name retained for exact-edition enrichment
    candidates: list[Book] = [seed]
    seed_title = _normalise(seed.title)
    seed_authors = {_normalise(author) for author in seed.authors if _normalise(author)}

    try:
        response = service.search(
            query=seed.title,
            mode="Title",
            provider="Both",
            max_results=24,
            language="",
            order_by="relevance",
            ebook_filter="",
            page_index=0,
        )
        for candidate in response.books:
            candidate_title = _normalise(candidate.title)
            candidate_authors = {_normalise(author) for author in candidate.authors if _normalise(author)}
            title_match = candidate_title == seed_title or (
                seed_title and candidate_title and (seed_title in candidate_title or candidate_title in seed_title)
            )
            author_match = not seed_authors or bool(seed_authors & candidate_authors)
            if title_match and author_match:
                candidates.append(candidate)
    except Exception:
        pass

    try:
        candidates.append(service.enrich_seed(book))
    except Exception:
        pass

    try:
        payload = merge_book_records(candidates).to_dict()
    except Exception:
        return book.to_dict()
    set_cached(database_path, "book-detail", parts, payload, DETAIL_TTL)
    return payload


@st.cache_data(ttl=60 * 30, show_spinner=False, max_entries=200)
def cached_similar(
    seed_payload: dict,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    limit: int = 12,
    engine_version: str = "v20-fast-similar",
    scan_mode: str = "Fast",
    database_path: str = "",
) -> tuple[list[dict], list[str]]:
    seed = Book.from_dict(seed_payload)
    mode = "Deep" if str(scan_mode).casefold() == "deep" else "Fast"
    parts = (seed.uid, limit, mode, engine_version, bool(google_api_key))
    cached = get_cached(database_path, "similar", *parts)
    if isinstance(cached, dict):
        return list(cached.get("books") or []), list(cached.get("messages") or [])

    service = BookSearchService(google_api_key, open_library_contact, timeout)
    enriched_seed = service.prepare_recommendation_seed(seed)
    response = service.recommendation_candidates(
        enriched_seed,
        max_results=150 if mode == "Deep" else 80,
        scan_mode=mode,
    )
    enriched_candidates = service.enrich_recommendation_candidates(
        enriched_seed,
        response.books,
        limit=12 if mode == "Deep" else 6,
        parallel=True,
    )
    ranked = rank_similar_detailed(enriched_seed, enriched_candidates, limit=limit)
    payloads = [
        {
            "book": result.book.to_dict(),
            "score": result.score,
            "match_percent": result.match_percent,
            "match_label": result.match_label,
            "reasons": list(result.reasons),
        }
        for result in ranked
    ]
    set_cached(
        database_path,
        "similar",
        parts,
        {"books": payloads, "messages": response.provider_messages},
        RECOMMENDATION_TTL,
    )
    return payloads, response.provider_messages


def _weighted_seed_books(profile_payload: dict, entry_payloads: list[dict], seed_limit: int) -> tuple[list[tuple[float, Book]], set[str], set[str]]:
    saved_uids: set[str] = set()
    saved_identities: set[str] = set()
    weighted: list[tuple[float, Book]] = []
    top_book_labels = {str(value).casefold() for value in profile_payload.get("top_books") or []}

    for entry in entry_payloads:
        try:
            book = Book.from_dict(entry.get("book") or {})
        except (TypeError, ValueError, KeyError):
            continue
        saved_uids.add(book.uid)
        saved_identities.add(_identity(book))
        shelf = str(entry.get("shelf") or "")
        rating = float(entry.get("user_rating") or 0.0)
        if shelf == "DNF" or (rating and rating <= 2.0):
            continue
        weight = 1.0
        if shelf == "Favourites":
            weight += 5.0
        elif shelf == "Finished":
            weight += 2.5
        elif shelf == "Reading":
            weight += 1.0
        if rating >= 4.5:
            weight += 5.0
        elif rating >= 4.0:
            weight += 3.0
        elif rating >= 3.5:
            weight += 1.0
        if f"{book.display_title} — {book.author_text}".casefold() in top_book_labels:
            weight += 5.0
        weighted.append((weight, book))

    weighted.sort(key=lambda item: item[0], reverse=True)
    unique: list[tuple[float, Book]] = []
    seen: set[str] = set()
    for item in weighted:
        if item[1].uid in seen:
            continue
        seen.add(item[1].uid)
        unique.append(item)
        if len(unique) >= seed_limit:
            break
    return unique, saved_uids, saved_identities


@st.cache_data(ttl=60 * 20, show_spinner=False, max_entries=200)
def cached_personalised(
    profile_payload: dict,
    entry_payloads: list[dict],
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    limit: int = 18,
    engine_version: str = "v20-parallel-persistent",
    refresh_token: int = 0,
    scan_mode: str = "Fast",
    database_path: str = "",
    feedback_payload: list[dict] | None = None,
) -> tuple[list[dict], list[str]]:
    mode = "Deep" if str(scan_mode).casefold() == "deep" else "Fast"
    seed_limit = 5 if mode == "Deep" else 3
    final_limit = max(6, min(int(limit), 30 if mode == "Deep" else 18))
    feedback_payload = list(feedback_payload or [])
    parts = (
        profile_payload,
        entry_payloads,
        bool(google_api_key),
        refresh_token,
        mode,
        feedback_payload,
        engine_version,
    )
    cached = get_cached(database_path, "personalised", *parts)
    if isinstance(cached, dict):
        return list(cached.get("books") or []), list(cached.get("messages") or [])

    weighted_seeds, saved_uids, saved_identities = _weighted_seed_books(
        profile_payload, entry_payloads, seed_limit
    )
    if not weighted_seeds:
        return [], ["No suitable finished, favourite or positively rated seed books were available."]

    negative_uids = {
        str(item.get("uid"))
        for item in feedback_payload
        if str(item.get("feedback")) in {"Not interested", "Hide this book", "Already read another edition"}
    }
    negative_identities = {
        f"{_normalise(str(item.get('title') or ''))}|{_normalise(str(item.get('author') or ''))}"
        for item in feedback_payload
        if str(item.get("feedback")) in {"Hide this book", "Already read another edition"}
        and (item.get("title") or item.get("author"))
    }
    hidden_authors = {
        _normalise(str(item.get("author") or ""))
        for item in feedback_payload
        if str(item.get("feedback")) == "Hide this author"
    }
    liked_authors = {
        _normalise(str(item.get("author") or ""))
        for item in feedback_payload
        if str(item.get("feedback")) in {"More like this", "Interested"}
    }
    preference_signals = {
        str(item.get("feedback"))
        for item in feedback_payload
        if str(item.get("feedback")) in {"Less romance", "More intense", "Lighter read"}
    }

    def preference_multiplier(book: Book) -> float:
        text = _normalise(
            " ".join(
                [
                    book.title,
                    book.subtitle,
                    book.description,
                    " ".join(book.categories),
                ]
            )
        )
        multiplier = 1.0
        romance_terms = ("romance", "romantic", "love story", "relationship")
        intense_terms = ("horror", "thriller", "dark", "violent", "gore", "extreme", "psychological")
        light_terms = ("cosy", "cozy", "uplifting", "humour", "humor", "feel good", "gentle", "comedy")
        if "Less romance" in preference_signals and any(term in text for term in romance_terms):
            multiplier -= 0.22
        if "More intense" in preference_signals:
            multiplier += 0.18 if any(term in text for term in intense_terms) else -0.05
        if "Lighter read" in preference_signals:
            if any(term in text for term in light_terms):
                multiplier += 0.18
            if any(term in text for term in intense_terms):
                multiplier -= 0.16
        return max(0.45, multiplier)

    def scan_seed(item: tuple[float, Book]) -> tuple[float, Book, list[Any], list[str]]:
        weight, seed = item
        service = BookSearchService(google_api_key, open_library_contact, timeout)
        enriched_seed = service.prepare_recommendation_seed(seed)
        try:
            response = service.recommendation_candidates(
                enriched_seed,
                max_results=145 if mode == "Deep" else 75,
                scan_mode=mode,
            )
        except TypeError:
            response = service.recommendation_candidates(
                enriched_seed,
                max_results=145 if mode == "Deep" else 75,
            )
        try:
            candidates = service.enrich_recommendation_candidates(
                enriched_seed,
                response.books,
                limit=12 if mode == "Deep" else 5,
                parallel=True,
            )
        except TypeError:
            candidates = service.enrich_recommendation_candidates(
                enriched_seed,
                response.books,
                limit=12 if mode == "Deep" else 5,
            )
        ranked = rank_similar_detailed(
            enriched_seed,
            candidates,
            limit=14 if mode == "Deep" else 9,
        )
        return weight, seed, ranked, response.provider_messages

    aggregates: dict[str, dict[str, Any]] = {}
    seed_buckets: list[list[str]] = []
    messages: list[str] = []

    workers = min(5 if mode == "Deep" else 3, len(weighted_seeds))
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="bookverse-seed") as executor:
        futures = [executor.submit(scan_seed, item) for item in weighted_seeds]
        for future in as_completed(futures):
            try:
                seed_weight, seed, ranked, provider_messages = future.result()
            except Exception as exc:
                messages.append(f"One recommendation seed could not be scanned: {exc}")
                continue
            messages.extend(provider_messages)
            bucket: list[str] = []
            for result in ranked:
                book = result.book
                if (
                    book.uid in saved_uids
                    or book.uid in negative_uids
                    or _identity(book) in saved_identities
                    or _identity(book) in negative_identities
                ):
                    continue
                author_key = _normalise(book.author_text)
                if author_key and author_key in hidden_authors:
                    continue
                record = aggregates.setdefault(
                    book.uid,
                    {
                        "book": book,
                        "score": 0.0,
                        "best_percent": 0,
                        "best_label": "Possible match",
                        "reasons": [],
                        "seed_count": 0,
                    },
                )
                multiplier = 1.0 + min(seed_weight, 12.0) * 0.08
                if author_key and author_key in liked_authors:
                    multiplier += 0.18
                multiplier *= preference_multiplier(book)
                record["score"] += float(result.score) * multiplier
                record["seed_count"] += 1
                if int(result.match_percent) > int(record["best_percent"]):
                    record["best_percent"] = int(result.match_percent)
                    record["best_label"] = str(result.match_label)
                for reason in [f"because you liked {seed.display_title}", *list(result.reasons)]:
                    if reason and reason not in record["reasons"]:
                        record["reasons"].append(reason)
                if book.uid not in bucket:
                    bucket.append(book.uid)
            if bucket:
                shift = (max(0, int(refresh_token)) * 2) % len(bucket) if refresh_token else 0
                seed_buckets.append(bucket[shift:] + bucket[:shift])

    # Niche searches fill genuine gaps, but Fast mode keeps them tightly bounded.
    niches = [str(value).strip() for value in profile_payload.get("favourite_niches") or [] if str(value).strip()]
    niche_limit = 5 if mode == "Deep" else 2

    def scan_niche(niche: str) -> tuple[str, list[Book], list[str]]:
        service = BookSearchService(google_api_key, open_library_contact, timeout)
        response = service.search(
            query=niche,
            mode="Genre / subject",
            provider="Auto" if mode == "Fast" else "Both",
            max_results=30 if mode == "Deep" else 18,
            language="en",
            order_by="relevance",
            ebook_filter="",
            page_index=refresh_token % 4,
        )
        return niche, response.books, response.provider_messages

    if len(aggregates) < final_limit * 2 and niches:
        with ThreadPoolExecutor(max_workers=min(3, niche_limit), thread_name_prefix="bookverse-niche") as executor:
            futures = [executor.submit(scan_niche, niche) for niche in niches[:niche_limit]]
            for future in as_completed(futures):
                try:
                    niche, books, provider_messages = future.result()
                except Exception:
                    continue
                messages.extend(provider_messages)
                for book in books:
                    if book.uid in saved_uids or book.uid in negative_uids or _identity(book) in saved_identities:
                        continue
                    author_key = _normalise(book.author_text)
                    if author_key and author_key in hidden_authors:
                        continue
                    record = aggregates.setdefault(
                        book.uid,
                        {
                            "book": book,
                            "score": 0.0,
                            "best_percent": 55,
                            "best_label": "Taste match",
                            "reasons": [],
                            "seed_count": 0,
                        },
                    )
                    record["score"] += (0.55 + (0.15 if author_key in liked_authors else 0.0)) * preference_multiplier(book)
                    if f"matches your {niche} preference" not in record["reasons"]:
                        record["reasons"].append(f"matches your {niche} preference")

    ordered_uids: list[str] = []
    # Round-robin preserves range across the reader's strongest books.
    while any(seed_buckets) and len(ordered_uids) < final_limit * 2:
        for bucket in seed_buckets:
            if bucket:
                uid = bucket.pop(0)
                if uid not in ordered_uids:
                    ordered_uids.append(uid)
    remaining = sorted(
        (uid for uid in aggregates if uid not in ordered_uids),
        key=lambda uid: (aggregates[uid]["seed_count"], aggregates[uid]["score"]),
        reverse=True,
    )
    ordered_uids.extend(remaining)

    payloads: list[dict] = []
    for uid in ordered_uids[:final_limit]:
        record = aggregates[uid]
        payloads.append(
            {
                "book": record["book"].to_dict(),
                "score": float(record["score"]),
                "match_percent": int(record["best_percent"]),
                "match_label": str(record["best_label"]),
                "reasons": list(record["reasons"][:5]),
                "seed_count": int(record["seed_count"]),
            }
        )
    messages = list(dict.fromkeys(message for message in messages if message))[:10]
    set_cached(
        database_path,
        "personalised",
        parts,
        {"books": payloads, "messages": messages},
        RECOMMENDATION_TTL,
    )
    return payloads, messages


@st.cache_data(ttl=60 * 30, show_spinner=False, max_entries=150)
def cached_mood_search(
    mood_query: str,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    min_rating: float = 0.0,
    max_pages: int = 0,
    standalone_only: bool = False,
    database_path: str = "",
    refresh_token: int = 0,
    year_from: int = 0,
    year_to: int = 0,
    series_preference: str = "Any",
) -> tuple[list[dict], list[str]]:
    query = mood_query.strip()
    if not query:
        return [], ["Describe the reading mood first."]
    parts = (
        query, min_rating, max_pages, standalone_only, year_from, year_to, series_preference,
        bool(google_api_key), refresh_token, "mood-v2",
    )
    cached = get_cached(database_path, "mood", *parts)
    if isinstance(cached, dict):
        return list(cached.get("books") or []), list(cached.get("messages") or [])

    service = BookSearchService(google_api_key, open_library_contact, timeout)
    response = service.search(
        query=query,
        mode="Keyword",
        provider="Both",
        max_results=54,
        language="en",
        order_by="relevance",
        ebook_filter="",
        page_index=max(0, int(refresh_token)) % 3,
    )
    plan = parse_smart_query(query)
    books = rank_smart_results(response.books, plan)
    filtered: list[Book] = []
    for book in books:
        if min_rating > 0 and (book.average_rating is None or book.average_rating < min_rating):
            continue
        if max_pages > 0 and book.page_count and book.page_count > max_pages:
            continue
        if year_from > 0 and book.published_year and book.published_year < year_from:
            continue
        if year_to > 0 and book.published_year and book.published_year > year_to:
            continue
        text = f"{book.title} {book.subtitle} {book.description} {' '.join(book.categories)}".casefold()
        looks_sequential = any(
            token in text
            for token in ("book 2", "book two", "book 3", "volume 2", "volume 3", "#2", "#3", "series")
        )
        if standalone_only or series_preference == "Standalone":
            if looks_sequential:
                continue
        elif series_preference == "Series" and not looks_sequential:
            continue
        filtered.append(book)
        if len(filtered) >= 18:
            break
    payloads = [book.to_dict() for book in filtered]
    set_cached(
        database_path,
        "mood",
        parts,
        {"books": payloads, "messages": response.provider_messages},
        RECOMMENDATION_TTL,
    )
    return payloads, response.provider_messages


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False, max_entries=700)
def cached_enrich_library_book(
    book_payload: dict,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    engine_version: str = "v20-library-details",
    database_path: str = "",
) -> dict:
    return cached_enrich_catalogue_book(
        book_payload,
        google_api_key,
        open_library_contact,
        timeout,
        engine_version,
        database_path,
    )
