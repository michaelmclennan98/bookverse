from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import streamlit as st

from .api_clients import BookSearchService, RequestBudget, merge_book_records
from .models import Book
from .persistent_cache import get_cached, set_cached
from .recommendation_intelligence import (
    book_dna,
    feedback_adjustment,
    final_match_percent,
    normalise_rules,
    recommendation_evidence_strength,
    rule_rejections,
    score_breakdown,
    select_diverse_records,
)
from .recommender import rank_similar_detailed, rank_smart_results
from .smart_search import parse_smart_query

SEARCH_TTL = 60 * 60 * 24 * 7
DETAIL_TTL = 60 * 60 * 24 * 30
RECOMMENDATION_TTL = 60 * 60 * 24 * 7
SEED_POOL_TTL = 60 * 60 * 24 * 7


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
    engine_version: str = "v21-recommendation-intelligence",
    refresh_token: int = 0,
    scan_mode: str = "Fast",
    database_path: str = "",
    feedback_payload: list[dict] | None = None,
    rules_payload: dict[str, Any] | None = None,
) -> tuple[list[dict], list[str]]:
    mode = "Deep" if str(scan_mode).casefold() == "deep" else "Fast"
    seed_limit = 5 if mode == "Deep" else 3
    final_limit = max(6, min(int(limit), 30 if mode == "Deep" else 18))
    feedback_payload = list(feedback_payload or [])
    rules = normalise_rules(rules_payload)
    parts = (
        profile_payload,
        entry_payloads,
        bool(google_api_key),
        refresh_token,
        mode,
        feedback_payload,
        rules,
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
        if str(item.get("feedback")) in {
            "Not interested", "Hide this book", "Already read another edition"
        }
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
        if str(item.get("feedback")) in {
            "Less romance", "More intense", "Lighter read", "Too much romance",
            "Not dark enough", "Too extreme", "Too long", "Too short",
            "Too old", "Wrong genre",
        }
    }

    # One shared budget applies to every worker in the scan. The provider clients
    # refuse further requests once the cap is reached and rank what is already held.
    request_budget = RequestBudget(
        max_google=30 if mode == "Deep" else 18,
        max_openlibrary=4 if mode == "Deep" else 2,
    )

    scan_stats: dict[str, int] = {
        "candidate_rows": 0,
        "saved_or_duplicate_removed": 0,
        "feedback_removed": 0,
        "hidden_author_removed": 0,
        "rule_filtered": 0,
        "weak_match_removed": 0,
        "aggregate_candidates": 0,
    }

    def scan_seed(item: tuple[float, Book]) -> tuple[float, Book, list[Any], list[str]]:
        weight, seed = item
        seed_cache_parts = (
            seed.uid,
            seed.to_dict(),
            mode,
            bool(google_api_key),
            "v21.1-seed-candidate-pool",
        )
        cached_pool = get_cached(database_path, "recommendation-seed-pool", *seed_cache_parts)
        provider_messages: list[str] = []

        if isinstance(cached_pool, dict) and cached_pool.get("candidates"):
            enriched_seed = Book.from_dict(cached_pool.get("seed") or seed.to_dict())
            candidates = [
                Book.from_dict(payload)
                for payload in cached_pool.get("candidates") or []
            ]
        else:
            service = BookSearchService(
                google_api_key,
                open_library_contact,
                timeout,
                request_budget=request_budget,
            )
            try:
                enriched_seed = service.prepare_recommendation_seed(seed, scan_mode=mode)
            except TypeError:
                enriched_seed = service.prepare_recommendation_seed(seed)
            try:
                response = service.recommendation_candidates(
                    enriched_seed,
                    max_results=80 if mode == "Deep" else 50,
                    scan_mode=mode,
                )
            except TypeError:
                response = service.recommendation_candidates(
                    enriched_seed,
                    max_results=80 if mode == "Deep" else 50,
                )
            provider_messages = list(response.provider_messages)
            try:
                candidates = service.enrich_recommendation_candidates(
                    enriched_seed,
                    response.books,
                    limit=3 if mode == "Deep" else 1,
                    parallel=True,
                )
            except TypeError:
                candidates = service.enrich_recommendation_candidates(
                    enriched_seed,
                    response.books,
                    limit=3 if mode == "Deep" else 1,
                )

            # Never cache an outage as an empty candidate pool. A successful pool is
            # reusable for seven days, so repeat refreshes rerank locally instead of
            # hitting both providers again.
            if candidates:
                set_cached(
                    database_path,
                    "recommendation-seed-pool",
                    seed_cache_parts,
                    {
                        "seed": enriched_seed.to_dict(),
                        "candidates": [book.to_dict() for book in candidates],
                    },
                    SEED_POOL_TTL,
                )

        ranked = rank_similar_detailed(
            enriched_seed,
            candidates,
            limit=18 if mode == "Deep" else 12,
        )
        return weight, seed, ranked, provider_messages

    aggregates: dict[str, dict[str, Any]] = {}
    messages: list[str] = []

    def has_defensible_match(seed: Book, result: Any) -> bool:
        evidence = recommendation_evidence_strength(seed, result.book)
        score = float(result.score)
        percent = int(result.match_percent)
        return (
            (percent >= 58 and score >= 0.12 and evidence >= 2)
            or (percent >= 54 and score >= 0.10 and evidence >= 4)
        )

    workers = min(3 if mode == "Deep" else 2, len(weighted_seeds))
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="bookverse-seed") as executor:
        futures = [executor.submit(scan_seed, item) for item in weighted_seeds]
        for future in as_completed(futures):
            try:
                seed_weight, seed, ranked, provider_messages = future.result()
            except Exception as exc:
                messages.append(f"One recommendation seed could not be scanned: {exc}")
                continue
            messages.extend(provider_messages)
            for result in ranked:
                scan_stats["candidate_rows"] += 1
                book = result.book
                if not has_defensible_match(seed, result):
                    scan_stats["weak_match_removed"] += 1
                    continue
                identity = _identity(book)
                if book.uid in saved_uids or identity in saved_identities:
                    scan_stats["saved_or_duplicate_removed"] += 1
                    continue
                if book.uid in negative_uids or identity in negative_identities:
                    scan_stats["feedback_removed"] += 1
                    continue
                author_key = _normalise(book.author_text)
                if author_key and author_key in hidden_authors:
                    scan_stats["hidden_author_removed"] += 1
                    continue
                rejections = rule_rejections(book, rules)
                if rejections:
                    scan_stats["rule_filtered"] += 1
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
                        "preference_points": 0.0,
                    },
                )
                multiplier = 1.0 + min(seed_weight, 12.0) * 0.08
                if author_key and author_key in liked_authors:
                    multiplier += 0.18
                    record["preference_points"] += 4.0
                feedback_multiplier, feedback_notes = feedback_adjustment(book, preference_signals)
                multiplier *= feedback_multiplier
                record["preference_points"] += (feedback_multiplier - 1.0) * 20.0
                record["score"] += float(result.score) * multiplier
                record["seed_count"] += 1
                if int(result.match_percent) > int(record["best_percent"]):
                    record["best_percent"] = int(result.match_percent)
                    record["best_label"] = str(result.match_label)
                for reason in [
                    f"because you liked {seed.display_title}",
                    *list(result.reasons),
                    *feedback_notes,
                ]:
                    if reason and reason not in record["reasons"]:
                        record["reasons"].append(reason)

    # A small profile-niche fallback runs only when seed scans did not produce a
    # healthy pool. Every niche result must still prove a match to a real seed.
    niches = [
        str(value).strip()
        for value in profile_payload.get("favourite_niches") or []
        if str(value).strip()
    ]
    niche_limit = 2 if mode == "Deep" else 1

    def scan_niche(niche: str) -> tuple[str, list[Book], list[str]]:
        service = BookSearchService(
            google_api_key,
            open_library_contact,
            timeout,
            request_budget=request_budget,
        )
        response = service.search(
            query=niche,
            mode="Genre / subject",
            provider="Auto",
            max_results=18 if mode == "Deep" else 12,
            language="en",
            order_by="relevance",
            ebook_filter="",
            page_index=refresh_token % 4,
        )
        return niche, response.books, response.provider_messages

    if len(aggregates) < final_limit * 2 and niches:
        with ThreadPoolExecutor(max_workers=min(2, niche_limit), thread_name_prefix="bookverse-niche") as executor:
            futures = [executor.submit(scan_niche, niche) for niche in niches[:niche_limit]]
            for future in as_completed(futures):
                try:
                    niche, books, provider_messages = future.result()
                except Exception:
                    continue
                messages.extend(provider_messages)
                for book in books:
                    scan_stats["candidate_rows"] += 1
                    identity = _identity(book)
                    if book.uid in saved_uids or identity in saved_identities:
                        scan_stats["saved_or_duplicate_removed"] += 1
                        continue
                    if book.uid in negative_uids or identity in negative_identities:
                        scan_stats["feedback_removed"] += 1
                        continue
                    author_key = _normalise(book.author_text)
                    if author_key and author_key in hidden_authors:
                        scan_stats["hidden_author_removed"] += 1
                        continue
                    if rule_rejections(book, rules):
                        scan_stats["rule_filtered"] += 1
                        continue

                    best_result = None
                    best_seed = None
                    for _seed_weight, seed_book in weighted_seeds:
                        ranked_one = rank_similar_detailed(seed_book, [book], limit=1)
                        if ranked_one and (
                            best_result is None
                            or float(ranked_one[0].score) > float(best_result.score)
                        ):
                            best_result = ranked_one[0]
                            best_seed = seed_book
                    if (
                        best_result is None
                        or best_seed is None
                        or not has_defensible_match(best_seed, best_result)
                    ):
                        scan_stats["weak_match_removed"] += 1
                        continue

                    record = aggregates.setdefault(
                        book.uid,
                        {
                            "book": book,
                            "score": 0.0,
                            "best_percent": int(best_result.match_percent),
                            "best_label": str(best_result.match_label),
                            "reasons": [],
                            "seed_count": 0,
                            "preference_points": 0.0,
                        },
                    )
                    multiplier, feedback_notes = feedback_adjustment(book, preference_signals)
                    if author_key in liked_authors:
                        multiplier += 0.15
                        record["preference_points"] += 3.0
                    record["preference_points"] += (multiplier - 1.0) * 20.0
                    record["score"] += float(best_result.score) * multiplier
                    record["seed_count"] += 1
                    record["best_percent"] = max(int(record["best_percent"]), int(best_result.match_percent))
                    for reason in [
                        f"matches your {niche} preference",
                        *list(best_result.reasons),
                        *feedback_notes,
                    ]:
                        if reason and reason not in record["reasons"]:
                            record["reasons"].append(reason)

    scan_stats["aggregate_candidates"] = len(aggregates)
    ranked_records = list(aggregates.values())
    for record in ranked_records:
        book = record["book"]
        record["rank_score"] = (
            int(record["best_percent"]) * 2.0
            + int(record["seed_count"]) * 12.0
            + float(record["score"]) * 18.0
            + (8.0 if book.description else 0.0)
            + min(int(book.ratings_count or 0), 1000) / 250.0
        )
    ranked_records.sort(key=lambda record: float(record["rank_score"]), reverse=True)
    if ranked_records and refresh_token:
        bucket = ranked_records
        shift = (max(0, int(refresh_token)) * 2) % len(bucket)
        ranked_records = bucket[shift:] + bucket[:shift]
    selected_records, diversity_stats = select_diverse_records(ranked_records, final_limit, rules)

    budget_stats = request_budget.snapshot()
    scan_report = {
        **scan_stats,
        **diversity_stats,
        **budget_stats,
        "seed_books": len(weighted_seeds),
        "final_recommendations": len(selected_records),
        "scan_mode": mode,
        "request_budget_total": int(budget_stats["google_budget"]) + int(budget_stats["openlibrary_budget"]),
        "request_attempts_total": int(budget_stats["google_attempts"]) + int(budget_stats["openlibrary_attempts"]),
    }

    payloads: list[dict] = []
    for record in selected_records:
        book = record["book"]
        breakdown = score_breakdown(record)
        match_percent = final_match_percent(record)
        payloads.append(
            {
                "book": book.to_dict(),
                "score": float(record["score"]),
                "match_percent": match_percent,
                "catalogue_match_percent": int(record["best_percent"]),
                "match_label": (
                    "Excellent taste match" if match_percent >= 85
                    else "Strong taste match" if match_percent >= 72
                    else "Good taste match"
                ),
                "reasons": list(record["reasons"][:6]),
                "seed_count": int(record["seed_count"]),
                "score_breakdown": breakdown,
                "dna": book_dna(book),
                "scan_report": scan_report,
            }
        )

    unique_messages = list(dict.fromkeys(message for message in messages if message))
    messages = []
    openlibrary_problem = any(
        "Open Library" in message
        and "budget reached" not in message.casefold()
        for message in unique_messages
    )
    google_problem = any(
        "Google Books" in message
        and "budget reached" not in message.casefold()
        for message in unique_messages
    )
    if openlibrary_problem:
        messages.append(
            "Open Library was temporarily limited. BookVerse continued with Google Books and saved seed pools."
        )
    if google_problem:
        messages.append(
            "One or more Google Books searches failed, but completed searches and saved seed pools were still ranked."
        )
    messages.extend(
        message for message in unique_messages
        if "Open Library" not in message
        and "Google Books" not in message
        and "budget reached" not in message.casefold()
    )
    messages = messages[:2]
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
