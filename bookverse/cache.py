from __future__ import annotations

import re

import streamlit as st

from .api_clients import BookSearchService, merge_book_records
from .models import Book
from .recommender import rank_similar_detailed


@st.cache_data(ttl=60 * 10, show_spinner=False, max_entries=300)
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
) -> tuple[list[dict], list[str]]:
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
    return [book.to_dict() for book in response.books], response.provider_messages


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False, max_entries=500)
def cached_enrich_catalogue_book(
    book_payload: dict,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    engine_version: str = "v19.2-catalogue-details",
) -> dict:
    """Retrieve and merge the richest exact title/author catalogue records."""
    _ = engine_version
    seed = Book.from_dict(book_payload)
    book = seed  # compatibility name used by the exact-enrichment path
    service = BookSearchService(google_api_key, open_library_contact, timeout)
    candidates: list[Book] = [seed]

    def norm(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

    seed_title = norm(seed.title)
    seed_authors = {norm(author) for author in seed.authors if norm(author)}

    try:
        response = service.search(
            query=seed.title,
            mode="Title",
            provider="Both",
            max_results=40,
            language="",
            order_by="relevance",
            ebook_filter="",
            page_index=0,
        )
        for candidate in response.books:
            candidate_title = norm(candidate.title)
            candidate_authors = {norm(author) for author in candidate.authors if norm(author)}
            title_match = candidate_title == seed_title or (
                seed_title and candidate_title and (
                    seed_title in candidate_title or candidate_title in seed_title
                )
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
        return merge_book_records(candidates).to_dict()
    except Exception:
        return book.to_dict()


@st.cache_data(ttl=60 * 30, show_spinner=False, max_entries=100)
def cached_similar(
    seed_payload: dict,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    limit: int = 12,
    engine_version: str = "v13-profiles-personalised",
) -> tuple[list[dict], list[str]]:
    _ = engine_version  # Explicitly versions the Streamlit cache key.
    seed = Book.from_dict(seed_payload)
    service = BookSearchService(google_api_key, open_library_contact, timeout)
    enriched_seed = service.prepare_recommendation_seed(seed)
    response = service.recommendation_candidates(enriched_seed, max_results=180)
    enriched_candidates = service.enrich_recommendation_candidates(enriched_seed, response.books, limit=14)
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
    return payloads, response.provider_messages


@st.cache_data(ttl=60 * 20, show_spinner=False, max_entries=100)
def cached_personalised(
    profile_payload: dict,
    entry_payloads: list[dict],
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
    limit: int = 18,
    engine_version: str = "v19.2-balanced-rich",
    refresh_token: int = 0,
) -> tuple[list[dict], list[str]]:
    """Build a balanced personalised set from the reader's exact books.

    Each strong saved book contributes recommendations in turn.  This prevents
    one richly-described seed (for example a mental-health novel) from taking
    over the whole first page when the reader also likes horror, thrillers or
    another distinct niche.  Duplicate Google/Open Library records are merged,
    and cards without a usable synopsis are hydrated before they are shown.
    """
    _ = engine_version
    refresh_token = max(0, int(refresh_token))
    service = BookSearchService(google_api_key, open_library_contact, timeout)
    saved_uids: set[str] = set()
    saved_identities: set[str] = set()
    weighted_seeds: list[tuple[float, Book]] = []

    def identity(book: Book) -> str:
        title = " ".join(re.findall(r"[a-z0-9]+", book.title.casefold()))
        author = " ".join(re.findall(r"[a-z0-9]+", book.author_text.casefold()))
        return f"{title}|{author}"
    top_book_labels = {str(value).casefold() for value in profile_payload.get("top_books") or []}

    for entry in entry_payloads:
        try:
            book = Book.from_dict(entry.get("book") or {})
        except (TypeError, ValueError, KeyError):
            continue
        saved_uids.add(book.uid)
        saved_identities.add(identity(book))
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

        exact_label = f"{book.display_title} — {book.author_text}".casefold()
        if exact_label in top_book_labels:
            weight += 5.0
        weighted_seeds.append((weight, book))

    weighted_seeds.sort(key=lambda item: item[0], reverse=True)
    unique_seeds: list[tuple[float, Book]] = []
    seen_seed_uids: set[str] = set()
    for item in weighted_seeds:
        if item[1].uid in seen_seed_uids:
            continue
        seen_seed_uids.add(item[1].uid)
        unique_seeds.append(item)
        if len(unique_seeds) >= 5:
            break

    aggregates: dict[str, dict] = {}
    seed_buckets: list[list[str]] = []
    messages: list[str] = []

    def add_result(result, seed: Book, seed_weight: float) -> str | None:
        book = result.book
        if book.uid in saved_uids or identity(book) in saved_identities:
            return None
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
        record["score"] += float(result.score) * multiplier
        record["seed_count"] += 1
        if int(result.match_percent) > int(record["best_percent"]):
            record["best_percent"] = int(result.match_percent)
            record["best_label"] = str(result.match_label)
        reason_values = [f"because you liked {seed.display_title}", *list(result.reasons)]
        for reason in reason_values:
            if reason and reason not in record["reasons"]:
                record["reasons"].append(reason)
        return book.uid

    for seed_weight, seed in unique_seeds:
        bucket: list[str] = []
        try:
            enriched_seed = service.prepare_recommendation_seed(seed)
            response = service.recommendation_candidates(enriched_seed, max_results=130)
            messages.extend(response.provider_messages)
            enriched_candidates = service.enrich_recommendation_candidates(
                enriched_seed, response.books, limit=12
            )
            ranked = rank_similar_detailed(enriched_seed, enriched_candidates, limit=14)
            for result in ranked:
                uid = add_result(result, seed, seed_weight)
                if uid and uid not in bucket:
                    bucket.append(uid)
        except Exception as exc:
            messages.append(f"Could not build matches from {seed.display_title}: {exc}")
        if bucket:
            # Refresh rotates within each seed's own matches rather than allowing
            # one seed to dominate the global ordering.
            shift = (refresh_token * 2) % len(bucket) if refresh_token else 0
            seed_buckets.append(bucket[shift:] + bucket[:shift])

    niche_bucket: list[str] = []
    if len(aggregates) < max(limit * 2, 30):
        for niche in [str(value).strip() for value in profile_payload.get("favourite_niches") or []][:5]:
            if not niche:
                continue
            try:
                response = service.search(
                    query=niche,
                    mode="Genre / subject",
                    provider="Both",
                    max_results=30,
                    language="en",
                    order_by="relevance",
                    ebook_filter="",
                    page_index=refresh_token % 4,
                )
                messages.extend(response.provider_messages)
            except Exception as exc:
                messages.append(f"Could not search favourite niche {niche}: {exc}")
                continue
            for position, book in enumerate(response.books):
                if book.uid in saved_uids or identity(book) in saved_identities:
                    continue
                record = aggregates.setdefault(
                    book.uid,
                    {
                        "book": book,
                        "score": 0.0,
                        "best_percent": 58,
                        "best_label": "Possible match",
                        "reasons": [],
                        "seed_count": 0,
                    },
                )
                rating_bonus = float(book.average_rating or 0.0) / 50.0
                record["score"] += max(0.04, 0.18 - position * 0.004) + rating_bonus
                niche_reason = f"matches your favourite niche: {niche}"
                if niche_reason not in record["reasons"]:
                    record["reasons"].append(niche_reason)
                if book.uid not in niche_bucket:
                    niche_bucket.append(book.uid)

    # Previous builds rotated the complete global list with:
    # shift = (refresh_token * 6) % len(ranked_records)
    # v19.2 instead rotates within each exact-book bucket so refresh remains
    # varied without letting one seed dominate every visible recommendation.
    ranked_records = sorted(
        aggregates.values(),
        key=lambda item: (
            float(item["score"]) + min(int(item["seed_count"]), 3) * 0.08,
            float(item["book"].average_rating or 0.0),
            int(item["book"].ratings_count or 0),
        ),
        reverse=True,
    )

    selected_records: list[dict] = []
    selected_uids: set[str] = set()
    author_counts: dict[str, int] = {}

    def prepare_record(record: dict) -> dict | None:
        book: Book = record["book"]
        if len(book.description.strip()) < 20:
            try:
                rich = service.enrich_seed(book)
                book = merge_book_records([book, rich])
                record["book"] = book
            except Exception:
                pass
        # Personalised browsing should feel complete.  Do not pad the feed with
        # thin records that have no real synopsis.
        if len(book.description.strip()) < 20:
            return None
        return record

    def try_select(uid: str) -> bool:
        if uid in selected_uids or uid not in aggregates:
            return False
        record = prepare_record(aggregates[uid])
        if record is None:
            return False
        book: Book = record["book"]
        author_key = book.author_text.casefold().strip() or "unknown"
        if author_counts.get(author_key, 0) >= 2:
            return False
        selected_uids.add(uid)
        author_counts[author_key] = author_counts.get(author_key, 0) + 1
        selected_records.append(record)
        return True

    # Round-robin across exact saved books.  The first visible batch therefore
    # represents the reader's different tastes instead of only the richest seed.
    if seed_buckets:
        max_depth = max(len(bucket) for bucket in seed_buckets)
        for depth in range(max_depth):
            for bucket in seed_buckets:
                if depth < len(bucket):
                    try_select(bucket[depth])
                    if len(selected_records) >= limit:
                        break
            if len(selected_records) >= limit:
                break

    if len(selected_records) < limit:
        for uid in niche_bucket:
            try_select(uid)
            if len(selected_records) >= limit:
                break

    if len(selected_records) < limit:
        for record in ranked_records:
            uid = record["book"].uid
            try_select(uid)
            if len(selected_records) >= limit:
                break

    output: list[dict] = []
    for record in selected_records:
        book: Book = record["book"]
        score = float(record["score"]) + min(int(record["seed_count"]), 3) * 0.08
        percent = max(
            55,
            min(94, int(record["best_percent"] or round(56 + min(score, 0.8) * 42))),
        )
        label = (
            "Strong match" if percent >= 84 else
            "Good match" if percent >= 70 else
            "Possible match"
        )
        output.append(
            {
                "book": book.to_dict(),
                "score": score,
                "match_percent": percent,
                "match_label": label,
                "reasons": list(record["reasons"][:6]),
            }
        )

    return output, list(dict.fromkeys(value for value in messages if value))


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False, max_entries=300)
def cached_enrich_library_book(
    book_payload: dict,
    google_api_key: str,
    open_library_contact: str,
    timeout: int,
) -> dict:
    """Return the richest matching catalogue record for a saved library book."""
    seed = Book.from_dict(book_payload)
    service = BookSearchService(google_api_key, open_library_contact, timeout)
    candidates: list[Book] = []
    if seed.source == "openlibrary":
        candidates.append(service.openlibrary.enrich_work(seed))
    try:
        response = service.search(
            query=seed.title, mode="Title", provider="Both", max_results=30,
            language="en", order_by="relevance", ebook_filter="", page_index=0,
        )
        candidates.extend(response.books)
    except Exception:
        pass

    seed_authors = {a.casefold().strip() for a in seed.authors}
    def score(book: Book) -> tuple[int, int, int, int]:
        authors = {a.casefold().strip() for a in book.authors}
        author_match = 1 if seed_authors and seed_authors.intersection(authors) else 0
        title_match = 1 if book.title.casefold().strip() == seed.title.casefold().strip() else 0
        richness = (len(book.description) // 80) + len(book.categories) + int(bool(book.publisher)) + int(bool(book.page_count))
        rating = int((book.ratings_count or 0) > 0)
        return (author_match, title_match, richness, rating)

    candidates.append(seed)
    candidates.sort(key=score, reverse=True)
    richest = candidates[0]
    base = seed.to_dict()
    rich = richest.to_dict()
    for field in (
        "subtitle", "description", "publisher", "published_date", "page_count", "language",
        "isbn10", "isbn13", "average_rating", "ratings_count", "thumbnail", "cover_url",
        "preview_link", "info_link", "buy_link", "is_ebook", "ebook_available", "public_domain",
    ):
        value = rich.get(field)
        if value not in (None, "", 0, False, []):
            base[field] = value
    if rich.get("authors"):
        base["authors"] = rich["authors"]
    if rich.get("categories"):
        combined=[]
        seen=set()
        for value in [*(base.get("categories") or []), *(rich.get("categories") or [])]:
            key=str(value).casefold()
            if value and key not in seen:
                combined.append(value); seen.add(key)
        base["categories"] = combined[:30]
    return base
