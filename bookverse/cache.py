from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import streamlit as st

from .api_clients import BookSearchService, RequestBudget, merge_book_records
from .models import Book
from .language_utils import book_language_status
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
from .recommender import profile_search_terms, rank_similar_detailed, rank_smart_results
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


REPAIRABLE_RULE_REASONS = {
    "missing a useful description",
    "not confirmed as English",
}


def _non_repairable_rule_rejections(book: Book, rules: dict[str, Any]) -> list[str]:
    return [
        reason for reason in rule_rejections(book, rules)
        if reason not in REPAIRABLE_RULE_REASONS
    ]


def _work_title_key(value: str) -> str:
    value = re.sub(
        r"\b(a novel|a novella|a memoir|stories|the complete edition|large print)\b",
        "",
        str(value or ""),
        flags=re.I,
    )
    return _normalise(value)


def _same_catalogue_work(left: Book, right: Book) -> bool:
    left_title = _work_title_key(left.title)
    right_title = _work_title_key(right.title)
    if not left_title or not right_title:
        return False
    title_match = (
        left_title == right_title
        or (len(left_title) >= 7 and left_title in right_title)
        or (len(right_title) >= 7 and right_title in left_title)
    )
    if not title_match:
        return False

    left_authors = {
        token
        for author in left.authors
        for token in _normalise(author).split()
        if len(token) >= 3
    }
    right_authors = {
        token
        for author in right.authors
        for token in _normalise(author).split()
        if len(token) >= 3
    }
    return not left_authors or not right_authors or bool(left_authors & right_authors)


def _repair_recommendation_candidate(
    book: Book,
    service: BookSearchService,
    database_path: str,
) -> Book:
    """Repair a promising candidate before strict description/language rules run.

    Exact Google title/author matching is attempted first. Open Library is used only
    as a final bounded fallback. Successful repairs persist for thirty days.
    """
    parts = (
        _identity(book),
        book.primary_isbn,
        "v21.2-candidate-metadata-repair",
        bool(service.google.enabled),
    )
    cached = get_cached(database_path, "recommendation-metadata-repair", *parts)
    if isinstance(cached, dict) and cached.get("title"):
        try:
            return Book.from_dict(cached)
        except (TypeError, ValueError, KeyError):
            pass

    candidates: list[Book] = [book]
    first_author = book.authors[0].strip() if book.authors else ""

    if service.google.enabled:
        exact_query = f'intitle:"{book.title}"'
        if first_author:
            exact_query += f' inauthor:"{first_author}"'
        try:
            response = service.search(
                query=exact_query,
                mode="Keyword",
                provider="Google Books",
                max_results=10,
                language="en",
                order_by="relevance",
                ebook_filter="",
                page_index=0,
            )
            candidates.extend(
                candidate for candidate in response.books
                if _same_catalogue_work(book, candidate)
            )
        except Exception:
            pass

    try:
        merged = merge_book_records(candidates)
    except Exception:
        merged = book

    needs_more = len(merged.description.strip()) < 20 or book_language_status(merged) == "unknown"
    if needs_more:
        try:
            response = service.search(
                query=book.title,
                mode="Title",
                provider="Open Library",
                max_results=12,
                language="en",
                order_by="relevance",
                ebook_filter="",
                page_index=0,
            )
            exact_openlibrary = [
                candidate for candidate in response.books
                if _same_catalogue_work(book, candidate)
            ]
            if exact_openlibrary:
                richest = max(
                    exact_openlibrary,
                    key=lambda candidate: (
                        len(candidate.description),
                        len(candidate.categories),
                    ),
                )
                if len(richest.description.strip()) < 20:
                    richest = service.openlibrary.enrich_work(richest)
                candidates.append(richest)
                merged = merge_book_records(candidates)
        except Exception:
            pass

    if (
        len(merged.description.strip()) >= 20
        or book_language_status(merged) != "unknown"
        or len(merged.categories) > len(book.categories)
    ):
        set_cached(
            database_path,
            "recommendation-metadata-repair",
            parts,
            merged.to_dict(),
            DETAIL_TTL,
        )
    return merged


@st.cache_data(ttl=60 * 20, show_spinner=False, max_entries=200)
def cached_personalised(
    profile_payload: dict,
    entry_payloads: list[dict],
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    limit: int = 18,
    engine_version: str = "v21.2-recommendation-recovery",
    refresh_token: int = 0,
    scan_mode: str = "Fast",
    database_path: str = "",
    feedback_payload: list[dict] | None = None,
    rules_payload: dict[str, Any] | None = None,
    attempt_token: int = 0,
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
        attempt_token,
        mode,
        feedback_payload,
        rules,
        engine_version,
    )
    cached = get_cached(database_path, "personalised", *parts)
    if isinstance(cached, dict) and cached.get("books"):
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

    # Separate budgets stop seed preparation and description repair from consuming
    # all requests before the actual recommendation searches have run.
    seed_budget = RequestBudget(
        max_google=7 if mode == "Deep" else 4,
        max_openlibrary=0,
    )
    search_budget = RequestBudget(
        max_google=28 if mode == "Deep" else 16,
        max_openlibrary=2 if mode == "Deep" else 1,
    )
    repair_budget = RequestBudget(
        max_google=14 if mode == "Deep" else 8,
        max_openlibrary=1,
    )

    scan_stats: dict[str, int] = {
        "candidate_rows": 0,
        "saved_or_duplicate_removed": 0,
        "feedback_removed": 0,
        "hidden_author_removed": 0,
        "rule_filtered": 0,
        "weak_match_removed": 0,
        "aggregate_candidates": 0,
        "expansion_queries": 0,
        "metadata_repairs_attempted": 0,
        "metadata_repairs_successful": 0,
    }

    def has_defensible_match(seed: Book, result: Any) -> bool:
        evidence = recommendation_evidence_strength(seed, result.book)
        score = float(result.score)
        percent = int(result.match_percent)
        return (
            (evidence >= 4 and score >= 0.075)
            or (evidence >= 2 and percent >= 54 and score >= 0.085)
            or (evidence >= 1 and percent >= 58 and score >= 0.11)
        )

    def scan_seed(item: tuple[float, Book]) -> tuple[float, Book, list[Any], list[str]]:
        weight, seed = item
        seed_cache_parts = (
            seed.uid,
            seed.to_dict(),
            mode,
            bool(google_api_key),
            "v21.2-seed-candidate-pool",
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
            seed_service = BookSearchService(
                google_api_key,
                open_library_contact,
                timeout,
                request_budget=seed_budget,
            )
            search_service = BookSearchService(
                google_api_key,
                open_library_contact,
                timeout,
                request_budget=search_budget,
            )
            try:
                enriched_seed = seed_service.prepare_recommendation_seed(seed, scan_mode=mode)
            except TypeError:
                enriched_seed = seed_service.prepare_recommendation_seed(seed)
            except Exception:
                enriched_seed = seed
            try:
                try:
                    response = search_service.recommendation_candidates(
                        enriched_seed,
                        max_results=120 if mode == "Deep" else 70,
                        scan_mode=mode,
                    )
                except TypeError:
                    response = search_service.recommendation_candidates(
                        enriched_seed,
                        max_results=120 if mode == "Deep" else 70,
                    )
                candidates = list(response.books)
                provider_messages = list(response.provider_messages)
            except Exception as exc:
                candidates = []
                provider_messages = [str(exc)]

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
            limit=30 if mode == "Deep" else 20,
        )
        return weight, enriched_seed, ranked, provider_messages

    aggregates: dict[str, dict[str, Any]] = {}
    messages: list[str] = []

    def add_ranked_candidate(
        seed_weight: float,
        seed: Book,
        result: Any,
        reason_prefix: str = "",
    ) -> None:
        scan_stats["candidate_rows"] += 1
        book = result.book
        if not has_defensible_match(seed, result):
            scan_stats["weak_match_removed"] += 1
            return
        identity = _identity(book)
        if book.uid in saved_uids or identity in saved_identities:
            scan_stats["saved_or_duplicate_removed"] += 1
            return
        if book.uid in negative_uids or identity in negative_identities:
            scan_stats["feedback_removed"] += 1
            return
        author_key = _normalise(book.author_text)
        if author_key and author_key in hidden_authors:
            scan_stats["hidden_author_removed"] += 1
            return
        if _non_repairable_rule_rejections(book, rules):
            scan_stats["rule_filtered"] += 1
            return

        record = aggregates.get(identity)
        if record is None:
            record = {
                "book": book,
                "score": 0.0,
                "best_percent": 0,
                "best_label": "Possible match",
                "reasons": [],
                "seed_count": 0,
                "matched_seed_uids": [],
                "preference_points": 0.0,
            }
            aggregates[identity] = record
        else:
            try:
                record["book"] = merge_book_records([record["book"], book])
            except Exception:
                pass

        multiplier = 1.0 + min(seed_weight, 12.0) * 0.08
        if author_key and author_key in liked_authors:
            multiplier += 0.18
            record["preference_points"] += 4.0
        feedback_multiplier, feedback_notes = feedback_adjustment(book, preference_signals)
        multiplier *= feedback_multiplier
        record["preference_points"] += (feedback_multiplier - 1.0) * 20.0
        record["score"] += float(result.score) * multiplier
        if seed.uid not in record["matched_seed_uids"]:
            record["matched_seed_uids"].append(seed.uid)
            record["seed_count"] += 1
        if int(result.match_percent) > int(record["best_percent"]):
            record["best_percent"] = int(result.match_percent)
            record["best_label"] = str(result.match_label)
        for reason in [
            reason_prefix or f"because you liked {seed.display_title}",
            *list(result.reasons),
            *feedback_notes,
        ]:
            if reason and reason not in record["reasons"]:
                record["reasons"].append(reason)

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
                add_ranked_candidate(seed_weight, seed, result)

    # A second, profile-wide stage widens the search only when the seed pools are
    # not large enough. It derives specific queries from the saved books rather
    # than relying on broad terms such as "fiction" or "dark" alone.
    generic_expansion_terms = {
        "fiction", "nonfiction", "general", "novel", "stories", "adult",
        "book", "literature", "dark", "mature", "suspenseful",
    }
    expansion_plan: list[tuple[str, str]] = []
    expansion_seen: set[tuple[str, str]] = set()

    def add_expansion(query: str, query_mode: str = "Keyword") -> None:
        query = " ".join(str(query or "").split()).strip()
        key = (query.casefold(), query_mode)
        if query and key not in expansion_seen:
            expansion_seen.add(key)
            expansion_plan.append((query, query_mode))

    for _weight, seed in weighted_seeds:
        terms = [
            term for term in profile_search_terms(seed, limit=8)
            if _normalise(term) not in generic_expansion_terms
            and len(_normalise(term)) >= 4
        ]
        if len(terms) >= 2:
            add_expansion(f"{terms[0]} {terms[1]} novel")
        if terms:
            add_expansion(terms[0], "Genre / subject")

    for niche in profile_payload.get("favourite_niches") or []:
        niche = str(niche).strip()
        if niche and _normalise(niche) not in generic_expansion_terms:
            add_expansion(f"{niche} novel")

    expansion_limit = 8 if mode == "Deep" else 4

    def scan_expansion(item: tuple[str, str]) -> tuple[list[Book], list[str]]:
        query, query_mode = item
        cache_parts = (
            query,
            query_mode,
            mode,
            bool(google_api_key),
            "v21.2-profile-expansion-pool",
        )
        cached_pool = get_cached(database_path, "recommendation-expansion-pool", *cache_parts)
        if isinstance(cached_pool, dict) and cached_pool.get("books"):
            return (
                [Book.from_dict(payload) for payload in cached_pool.get("books") or []],
                [],
            )
        service = BookSearchService(
            google_api_key,
            open_library_contact,
            timeout,
            request_budget=search_budget,
        )
        response = service.search(
            query=query,
            mode=query_mode,  # type: ignore[arg-type]
            provider="Auto",
            max_results=20,
            language="en",
            order_by="relevance",
            ebook_filter="",
            # The old engine used page_index=refresh_token % 4. The recovery
            # engine keeps expansion on page zero so every attempt starts with
            # the strongest catalogue results; attempt_token still bypasses a
            # previously failed cache entry.
            page_index=0,
        )
        if response.books:
            set_cached(
                database_path,
                "recommendation-expansion-pool",
                cache_parts,
                {"books": [book.to_dict() for book in response.books]},
                SEED_POOL_TTL,
            )
        return list(response.books), list(response.provider_messages)

    if len(aggregates) < final_limit * 3 and expansion_plan:
        selected_expansions = expansion_plan[:expansion_limit]
        scan_stats["expansion_queries"] = len(selected_expansions)
        with ThreadPoolExecutor(max_workers=min(3, len(selected_expansions)), thread_name_prefix="bookverse-expand") as executor:
            future_map = {
                executor.submit(scan_expansion, item): item
                for item in selected_expansions
            }
            for future in as_completed(future_map):
                query, _query_mode = future_map[future]
                try:
                    books, provider_messages = future.result()
                except Exception as exc:
                    messages.append(str(exc))
                    continue
                messages.extend(provider_messages)
                for book in books:
                    best: tuple[float, Book, Any] | None = None
                    for seed_weight, seed in weighted_seeds:
                        ranked_one = rank_similar_detailed(seed, [book], limit=1)
                        if not ranked_one:
                            continue
                        result = ranked_one[0]
                        if best is None or float(result.score) > float(best[2].score):
                            best = (seed_weight, seed, result)
                    if best is not None:
                        add_ranked_candidate(
                            best[0],
                            best[1],
                            best[2],
                            reason_prefix=f"found through {query}",
                        )

    scan_stats["aggregate_candidates"] = len(aggregates)

    # Repair only the strongest promising candidates, then enforce every active rule.
    provisional = list(aggregates.values())
    for record in provisional:
        book = record["book"]
        record["pre_rank"] = (
            int(record["best_percent"]) * 2.0
            + int(record["seed_count"]) * 12.0
            + float(record["score"]) * 18.0
            + (8.0 if book.description else 0.0)
            + min(int(book.ratings_count or 0), 1000) / 250.0
        )
    provisional.sort(key=lambda record: float(record["pre_rank"]), reverse=True)

    repair_limit = min(len(provisional), 40 if mode == "Deep" else 24)
    repair_targets = [
        record for record in provisional[:repair_limit]
        if any(reason in REPAIRABLE_RULE_REASONS for reason in rule_rejections(record["book"], rules))
    ]
    scan_stats["metadata_repairs_attempted"] = len(repair_targets)

    def repair_record(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        original: Book = record["book"]
        service = BookSearchService(
            google_api_key,
            open_library_contact,
            timeout,
            request_budget=repair_budget,
        )
        repaired = _repair_recommendation_candidate(original, service, database_path)
        changed = (
            len(repaired.description) > len(original.description)
            or book_language_status(repaired) != book_language_status(original)
            or len(repaired.categories) > len(original.categories)
        )
        updated = dict(record)
        updated["book"] = repaired
        return updated, changed

    repaired_by_identity: dict[str, dict[str, Any]] = {}
    if repair_targets:
        with ThreadPoolExecutor(max_workers=min(3, len(repair_targets)), thread_name_prefix="bookverse-repair") as executor:
            future_map = {
                executor.submit(repair_record, record): _identity(record["book"])
                for record in repair_targets
            }
            for future in as_completed(future_map):
                identity = future_map[future]
                try:
                    repaired_record, changed = future.result()
                except Exception:
                    continue
                repaired_by_identity[identity] = repaired_record
                if changed:
                    scan_stats["metadata_repairs_successful"] += 1

    final_records: list[dict[str, Any]] = []
    for record in provisional:
        identity = _identity(record["book"])
        record = repaired_by_identity.get(identity, record)
        book = record["book"]
        rejections = rule_rejections(book, rules)
        if rejections:
            scan_stats["rule_filtered"] += 1
            continue
        record["rank_score"] = (
            int(record["best_percent"]) * 2.0
            + int(record["seed_count"]) * 12.0
            + float(record["score"]) * 18.0
            + (10.0 if len(book.description) >= 120 else 6.0)
            + min(int(book.ratings_count or 0), 1000) / 250.0
        )
        final_records.append(record)

    final_records.sort(key=lambda record: float(record["rank_score"]), reverse=True)
    # Legacy rotation formula retained for compatibility and auditability:
    # shift = (max(0, int(refresh_token)) * 2) % len(bucket)
    if final_records and refresh_token:
        safe_head = final_records[: max(final_limit, 12)]
        tail = final_records[max(final_limit, 12):]
        if tail:
            shift = (max(0, int(refresh_token)) * 2) % len(tail)
            final_records = safe_head + tail[shift:] + tail[:shift]

    selected_records, diversity_stats = select_diverse_records(final_records, final_limit, rules)

    snapshots = [seed_budget.snapshot(), search_budget.snapshot(), repair_budget.snapshot()]
    budget_stats: dict[str, int] = {}
    for key in (
        "google_attempts", "google_successes", "google_errors", "google_denied",
        "openlibrary_attempts", "openlibrary_successes", "openlibrary_errors", "openlibrary_denied",
        "google_budget", "openlibrary_budget",
    ):
        budget_stats[key] = sum(int(snapshot.get(key, 0)) for snapshot in snapshots)

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
    condensed: list[str] = []
    if any("Open Library" in message for message in unique_messages):
        condensed.append(
            "Open Library was limited during part of the scan. Google Books and saved candidate pools completed the remaining work."
        )
    if any("Google Books" in message for message in unique_messages):
        condensed.append(
            "Some Google Books requests did not complete, but other searches and saved candidate pools were still ranked."
        )
    condensed.extend(
        message for message in unique_messages
        if "Open Library" not in message
        and "Google Books" not in message
        and "budget reached" not in message.casefold()
    )
    messages = list(dict.fromkeys(condensed))[:2]

    # Never persist an empty outage result. Failed attempts must be allowed to run
    # again immediately instead of replaying an empty cache for seven days.
    if payloads:
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
