from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Book, clean_text, unique_strings
from .language_utils import is_english_book
from .recommender import HIGH_SPECIFICITY_THEMES, GENERIC_CATEGORIES, profile_book, profile_search_terms

LOGGER = logging.getLogger(__name__)
SearchMode = Literal["Keyword", "Title", "Author", "Genre / subject", "ISBN"]
Provider = Literal["Auto", "Both", "Google Books", "Open Library"]


class BookAPIError(RuntimeError):
    """Raised when an external book provider cannot complete a request."""


@dataclass(slots=True)
class SearchResponse:
    books: list[Book]
    provider_messages: list[str]


def build_http_session(user_agent: str, retries: int = 3) -> requests.Session:
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class GoogleBooksClient:
    BASE_URL = "https://www.googleapis.com/books/v1/volumes"
    COOLDOWN_SECONDS = 180
    _cooldown_until = 0.0

    def __init__(self, api_key: str, timeout: int = 15) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        # Google occasionally returns bursts of 503 responses. Keep retries low and
        # temporarily pause further Google calls so Open Library can take over quickly.
        self.session = build_http_session("BookVerse/0.1 GoogleBooksClient", retries=1)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        query: str,
        mode: SearchMode = "Keyword",
        max_results: int = 30,
        start_index: int = 0,
        language: str = "",
        order_by: str = "relevance",
        ebook_filter: str = "",
    ) -> list[Book]:
        if not self.enabled:
            return []
        if time.monotonic() < type(self)._cooldown_until:
            raise BookAPIError("Google Books is temporarily unavailable. Open Library results are being used.")
        field_prefix = {
            "Title": "intitle:",
            "Author": "inauthor:",
            "Genre / subject": "subject:",
            "ISBN": "isbn:",
        }.get(mode, "")
        q = f"{field_prefix}{query.strip()}" if field_prefix else query.strip()
        params: dict[str, Any] = {
            "q": q,
            "key": self.api_key,
            # Smaller requests are more reliable and Open Library fills the remainder.
            "maxResults": max(1, min(max_results, 20)),
            "startIndex": max(0, start_index),
            "orderBy": order_by if order_by in {"relevance", "newest"} else "relevance",
            "printType": "books",
            "projection": "full",
        }
        if language:
            params["langRestrict"] = language
        if ebook_filter:
            params["filter"] = ebook_filter
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            type(self)._cooldown_until = time.monotonic() + self.COOLDOWN_SECONDS
            LOGGER.warning("Google Books temporarily unavailable: %s", type(exc).__name__)
            # Never include the request URL because it contains the API key.
            raise BookAPIError("Google Books is temporarily unavailable. Open Library results are being used.") from exc
        return [Book.from_google(item) for item in payload.get("items") or []]


class OpenLibraryClient:
    BASE_URL = "https://openlibrary.org/search.json"
    WORK_URL = "https://openlibrary.org/works/{work_id}.json"

    def __init__(self, contact: str, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = build_http_session(f"BookVerse/0.1 ({contact})")

    def search(
        self,
        query: str,
        mode: SearchMode = "Keyword",
        max_results: int = 40,
        page: int = 1,
        language: str = "",
        sort: str = "",
    ) -> list[Book]:
        field = {
            "Keyword": "q",
            "Title": "title",
            "Author": "author",
            "Genre / subject": "subject",
            "ISBN": "isbn",
        }.get(mode, "q")
        params: dict[str, Any] = {
            field: query.strip(),
            "page": max(1, page),
            "limit": max(1, min(max_results, 100)),
            "fields": ",".join(
                [
                    "key", "title", "subtitle", "author_name", "first_publish_year",
                    "isbn", "cover_i", "cover_edition_key", "subject", "publisher",
                    "number_of_pages_median", "language", "ratings_average", "publish_year",
                    "ratings_count", "ebook_access", "first_sentence",
                ]
            ),
        }
        if language:
            # Google Books uses two-letter language codes ("en"), while
            # Open Library normally indexes English as the three-letter code
            # "eng". Mapping here prevents valid English title searches from
            # returning an empty catalogue result.
            params["language"] = "eng" if language.casefold() in {"en", "english"} else language
        if sort:
            params["sort"] = sort
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BookAPIError(f"Open Library request failed: {exc}") from exc
        return [Book.from_openlibrary(doc) for doc in payload.get("docs") or []]

    def enrich_work(self, book: Book) -> Book:
        """Fetch the richer Open Library work record for one search result."""
        if book.source != "openlibrary" or not book.source_id.startswith("OL"):
            return book
        try:
            response = self.session.get(
                self.WORK_URL.format(work_id=book.source_id),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return book

        data = book.to_dict()
        description = clean_text(payload.get("description"))
        if description and len(description) > len(book.description):
            data["description"] = description
        subjects = unique_strings(payload.get("subjects") or [], 30)
        if subjects:
            data["categories"] = list(unique_strings([*book.categories, *subjects], 30))
        first_publish = clean_text(payload.get("first_publish_date"))
        if first_publish and not data.get("published_date"):
            data["published_date"] = first_publish
        covers = payload.get("covers") or []
        cover_id = next((value for value in covers if isinstance(value, int) and value > 0), None)
        if cover_id and not data.get("cover_url"):
            data["cover_url"] = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
            data["thumbnail"] = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
        return Book.from_dict(data)


class BookSearchService:
    def __init__(
        self,
        google_api_key: str = "",
        open_library_contact: str = "bookverse-local@example.invalid",
        timeout: int = 15,
    ) -> None:
        self.google = GoogleBooksClient(google_api_key, timeout)
        self.openlibrary = OpenLibraryClient(open_library_contact, timeout)

    def search(
        self,
        query: str,
        mode: SearchMode = "Keyword",
        provider: Provider = "Auto",
        max_results: int = 36,
        language: str = "",
        order_by: str = "relevance",
        ebook_filter: str = "",
        page_index: int = 0,
    ) -> SearchResponse:
        query = query.strip()
        if not query:
            return SearchResponse([], ["Enter a title, author, genre, ISBN or description."])

        use_google = provider in {"Both", "Google Books"} or (provider == "Auto" and self.google.enabled)
        use_openlibrary = provider in {"Both", "Open Library"} or provider == "Auto"
        messages: list[str] = []
        books: list[Book] = []

        if use_google:
            if not self.google.enabled:
                messages.append("Google Books was skipped because no API key is configured.")
            else:
                try:
                    books.extend(
                        self.google.search(
                            query=query,
                            mode=mode,
                            max_results=min(max_results, 20),
                            language=language,
                            order_by=order_by,
                            ebook_filter=ebook_filter,
                            start_index=max(0, int(page_index)) * min(max_results, 20),
                        )
                    )
                except BookAPIError as exc:
                    LOGGER.warning("Google Books error: %s", exc)
                    # Auto/Both should fall back quietly. Only show a friendly message
                    # when the user explicitly selected Google Books alone.
                    if provider == "Google Books":
                        messages.append(str(exc))

        if use_openlibrary:
            try:
                books.extend(
                    self.openlibrary.search(
                        query=query,
                        mode=mode,
                        max_results=max_results,
                        language=language,
                        sort="new" if order_by == "newest" else "",
                        page=max(1, int(page_index) + 1),
                    )
                )
            except BookAPIError as exc:
                LOGGER.warning("Open Library error: %s", exc)
                messages.append(str(exc))

        return SearchResponse(deduplicate_books(books)[:max_results], messages)


    def enrich_seed(self, seed: Book) -> Book:
        """Fetch richer metadata for the exact title/author before recommending."""
        matches: list[Book] = [seed]
        title = seed.title.strip()
        author = seed.authors[0].strip() if seed.authors else ""

        if self.google.enabled and title:
            queries = [f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")]
            for query in queries:
                try:
                    matches.extend(self.google.search(query, mode="Keyword", max_results=12))
                except BookAPIError:
                    pass

        if title:
            try:
                matches.extend(self.openlibrary.search(title, mode="Title", max_results=20))
            except BookAPIError:
                pass

        def norm(value: str) -> str:
            return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

        seed_title = norm(seed.title)
        seed_authors = {norm(a) for a in seed.authors if a}
        relevant: list[Book] = []
        for book in matches:
            bt = norm(book.title)
            ba = {norm(a) for a in book.authors if a}
            title_match = bt == seed_title or seed_title in bt or bt in seed_title
            author_match = not seed_authors or bool(seed_authors & ba)
            if title_match and author_match:
                relevant.append(book)

        if not relevant:
            return seed
        # Search records often contain only a first sentence. Fetch at most two exact
        # Open Library work records to recover a full description and subjects.
        hydrated: list[Book] = []
        fetched = 0
        for book in relevant:
            if book.source == "openlibrary" and fetched < 2:
                hydrated.append(self.openlibrary.enrich_work(book))
                fetched += 1
            else:
                hydrated.append(book)
        return merge_book_records(hydrated)


    def author_profile(self, seed: Book) -> tuple[list[str], str]:
        """Infer stable catalogue signals from the author's wider body of work.

        This is only used for sparse editions. A signal must recur across several
        works, so one unusual title cannot redefine the selected book.
        """
        if not seed.authors:
            return [], ""
        author = seed.authors[0].strip()
        if not author:
            return [], ""

        works: list[Book] = []
        try:
            works.extend(self.openlibrary.search(author, mode="Author", max_results=45))
        except BookAPIError:
            pass
        if self.google.enabled:
            try:
                works.extend(self.google.search(author, mode="Author", max_results=20))
            except BookAPIError:
                pass
        works = deduplicate_books(works)[:30]
        if not works:
            return [], ""

        signal_counts: dict[str, int] = {}
        descriptions: list[tuple[Book, set[str]]] = []
        horror_works = 0
        intensity_works = 0
        explicit_extreme_works = 0
        romance_works = 0
        fantasy_works = 0
        psychological_works = 0

        intensity_terms = re.compile(
            r"\b(extreme|splatterpunk|hardcore horror|graphic violence|gore|gory|brutal|"
            r"sadistic|torture|carnage|blood-soaked|depraved|transgressive|mutilat|slaughter)\b",
            re.I,
        )
        for work in works:
            profile = profile_book(work)
            audience_signals = set(profile.target_audiences)
            raw_corpus = " ".join([work.title, work.subtitle, work.description, *work.categories]).casefold()
            # Do not let the fallback "adult" label become an author's stable identity.
            # Count adult only when the record explicitly says so or carries mature content.
            if (
                "adult" in audience_signals
                and not re.search(r"\b(adult fiction|adult novel|for adults|mature readers|18\+)\b", raw_corpus)
                and profile.content_level not in {"mature", "extreme"}
            ):
                audience_signals.discard("adult")
            signals = (
                profile.genres | profile.subgenres | profile.themes | profile.tones |
                profile.work_types | audience_signals
            )
            for signal in signals:
                signal_counts[signal] = signal_counts.get(signal, 0) + 1
            if work.description:
                descriptions.append((work, signals))
            corpus = " ".join([work.title, work.subtitle, work.description, *work.categories])
            if "horror" in profile.genres:
                horror_works += 1
            if intensity_terms.search(corpus):
                intensity_works += 1
            if "extreme_horror" in profile.subgenres or re.search(r"\b(extreme horror|splatterpunk)\b", corpus, re.I):
                explicit_extreme_works += 1
            if "romance" in profile.genres:
                romance_works += 1
            if "fantasy" in profile.genres:
                fantasy_works += 1
            if "psychological_horror" in profile.subgenres or "psychological_thriller" in profile.subgenres:
                psychological_works += 1

        threshold = max(2, min(4, round(len(works) * 0.15)))
        stable = {
            signal for signal, count in signal_counts.items()
            if count >= threshold
        }
        if not stable:
            stable = {
                signal for signal, count in sorted(
                    signal_counts.items(), key=lambda item: item[1], reverse=True
                )[:10] if count >= 2
            }

        # General body-of-work inference for catalogue labels that APIs commonly omit.
        # These are author-level signatures, not hardcoded author or title exceptions.
        if horror_works >= max(2, round(len(works) * 0.25)):
            stable.add("horror")
            if explicit_extreme_works >= 1 or intensity_works >= max(2, round(horror_works * 0.25)):
                stable.update({"extreme_horror", "violent", "adult", "novel"})
        if romance_works >= max(2, round(len(works) * 0.30)) and fantasy_works >= max(2, round(len(works) * 0.25)):
            stable.update({"romance", "fantasy", "romantasy"})
        if psychological_works >= 2:
            stable.add("suspenseful")

        categories = [signal.replace("_", " ") for signal in sorted(stable)]
        selected_descriptions = [
            work.description for work, signals in descriptions
            if signals & stable and len(work.description) >= 80
        ][:5]
        return categories[:28], " ".join(selected_descriptions)[:3500]

    def prepare_recommendation_seed(self, seed: Book) -> Book:
        """Enrich an exact edition and cautiously fill sparse metadata from its author."""
        if seed.source == "bookverse":
            return seed
        enriched = self.enrich_seed(seed)
        profile = profile_book(enriched)
        meaningful_categories = [
            c for c in enriched.categories if c.casefold().strip() not in GENERIC_CATEGORIES
        ]
        needs_author_context = (
            profile.confidence < 0.62
            or len(enriched.description) < 100
            or len(meaningful_categories) < 2
            or (
                "horror" in profile.genres
                and "adult" not in profile.target_audiences
                and profile.content_level_value <= 2
                and (len(enriched.description) < 500 or len(meaningful_categories) < 4)
            )
        )
        if not needs_author_context:
            return enriched

        author_categories, author_text = self.author_profile(enriched)
        if not author_categories and not author_text:
            return enriched

        payload = enriched.to_dict()
        category_values: list[str] = list(enriched.categories)
        seen = {value.casefold() for value in category_values}
        for value in author_categories:
            if value.casefold() not in seen:
                seen.add(value.casefold())
                category_values.append(value)
        payload["categories"] = category_values[:24]
        if len(enriched.description) < 220 and author_text:
            payload["description"] = " ".join(
                part for part in (enriched.description, author_text) if part
            )[:4200]
        return Book.from_dict(payload)

    def enrich_recommendation_candidates(
        self,
        seed: Book,
        candidates: list[Book],
        limit: int = 14,
    ) -> list[Book]:
        """Hydrate the most promising Open Library works before final ranking.

        Search results often contain only a first sentence. Fetching a bounded number
        of full work records greatly improves fiction/nonfiction and book-type checks
        without turning one recommendation request into hundreds of API calls.
        """
        seed_profile = profile_book(seed)
        scored: list[tuple[float, Book]] = []
        for book in candidates:
            profile = profile_book(book)
            score = 0.0
            score += 4.0 * len(seed_profile.subgenres & profile.subgenres)
            score += 2.2 * len(seed_profile.genres & profile.genres)
            score += 1.5 * len(seed_profile.themes & profile.themes)
            score += 2.6 * len(
                (seed_profile.themes & profile.themes) & HIGH_SPECIFICITY_THEMES
            )
            score += 0.8 * len(seed_profile.tones & profile.tones)
            if seed_profile.primary_work_type == profile.primary_work_type != "unknown":
                score += 2.0
            if book.description:
                score += min(len(book.description), 300) / 600
            if book.source == "openlibrary":
                score += 0.25
            scored.append((score, book))
        scored.sort(key=lambda row: row[0], reverse=True)

        hydrate_ids: set[str] = set()
        for _score, book in scored:
            if book.source == "openlibrary":
                hydrate_ids.add(book.uid)
                if len(hydrate_ids) >= limit:
                    break
        enriched: list[Book] = []
        for book in candidates:
            if book.uid in hydrate_ids:
                enriched.append(self.openlibrary.enrich_work(book))
            else:
                enriched.append(book)
        return deduplicate_books(enriched)

    def recommendation_candidates(self, seed: Book, max_results: int = 160) -> SearchResponse:
        """Build a broad candidate pool, then let the recommender enforce precision.

        Queries are generated from the seed's strongest subgenres, genres, themes,
        tones and weighted metadata. This works across fiction and nonfiction rather
        than relying on special cases for one author or one genre.
        """
        search_terms = profile_search_terms(seed, limit=10)
        profile = profile_book(seed)
        # The current app is English-first. Provider-level language constraints
        # reduce irrelevant editions before the local language validator runs.
        google_language = "en"
        openlibrary_language = "eng"
        messages: list[str] = []
        all_books: list[Book] = []

        query_plan: list[tuple[str, SearchMode]] = []

        def add_query(query: str, mode: SearchMode = "Keyword") -> None:
            query = query.strip()
            key = (query.casefold(), mode)
            if query and key not in {(q.casefold(), m) for q, m in query_plan}:
                query_plan.append((query, mode))

        # Specific combinations find niche matches; individual terms preserve recall.
        specific = [value.replace("_", " ") for value in sorted(profile.subgenres)]
        themes = [
            value.replace("_", " ")
            for value in [
                *sorted(profile.themes & HIGH_SPECIFICITY_THEMES),
                *sorted(profile.themes - HIGH_SPECIFICITY_THEMES),
            ]
        ]
        genres = [value.replace("_", " ") for value in sorted(profile.genres)]
        tones = [value.replace("_", " ") for value in sorted(profile.tones)]
        work_type = profile.primary_work_type.replace("_", " ") if profile.primary_work_type != "unknown" else ""
        audience = (
            "adult" if "adult" in profile.target_audiences
            else "young adult" if "young_adult" in profile.target_audiences
            else "middle grade" if "middle_grade" in profile.target_audiences
            else "children" if "children" in profile.target_audiences
            else ""
        )
        content_term = (
            "extreme horror" if profile.content_level == "extreme" and "horror" in profile.genres
            else "mature" if profile.content_level == "mature"
            else ""
        )
        if specific:
            add_query(" ".join(value for value in [specific[0], work_type, audience, content_term, *(themes[:1] or tones[:1])] if value))
        if genres and themes:
            add_query(" ".join(value for value in [genres[0], work_type, themes[0]] if value))
        if genres and tones:
            add_query(" ".join(value for value in [genres[0], work_type, tones[0]] if value))
        if genres and work_type:
            add_query(" ".join(value for value in [genres[0], work_type, audience, content_term] if value))
        for value in specific[:3]:
            add_query(value, "Genre / subject")
            add_query(value, "Keyword")
        for value in genres[:3]:
            add_query(value, "Genre / subject")
        for value in search_terms[:5]:
            add_query(value, "Keyword")

        # A sparse book can still surface its author's nearby works and improve recall.
        if seed.authors:
            add_query(seed.authors[0], "Author")
        if not query_plan:
            add_query(seed.title, "Title")

        # Open Library is the resilient high-recall source. Keep the query count bounded.
        for query, mode in query_plan[:7]:
            try:
                all_books.extend(
                    self.openlibrary.search(
                        query,
                        mode=mode,
                        max_results=36,
                        language=openlibrary_language,
                    )
                )
            except BookAPIError as exc:
                messages.append(str(exc))

        # Google usually has richer descriptions. A few focused requests are enough;
        # its existing cooldown handles temporary 503 responses without breaking results.
        if self.google.enabled:
            google_queries = [item for item in query_plan if item[1] != "Author"][:3]
            for query, mode in google_queries:
                try:
                    all_books.extend(
                        self.google.search(
                            query,
                            mode=mode,
                            max_results=20,
                            language=google_language,
                        )
                    )
                except BookAPIError as exc:
                    LOGGER.warning("Recommendation Google Books error: %s", exc)
                    break

        deduplicated = deduplicate_books(all_books)
        english_candidates = [
            book for book in deduplicated
            if is_english_book(book, allow_unknown=True)
        ]
        return SearchResponse(english_candidates[:max_results], _unique(messages))



def merge_book_records(books: list[Book]) -> Book:
    """Combine matching editions, preferring the richest non-empty metadata."""
    if not books:
        raise ValueError("books cannot be empty")

    def richness(book: Book) -> tuple[int, int, int, int]:
        return (len(book.description), len(book.categories), int(bool(book.best_cover)), book.ratings_count)

    base = max(books, key=richness)
    descriptions = sorted((b.description for b in books if b.description), key=len, reverse=True)
    categories: list[str] = []
    seen: set[str] = set()
    for book in books:
        for category in book.categories:
            key = category.casefold()
            if key not in seen:
                seen.add(key); categories.append(category)

    payload = base.to_dict()
    payload["description"] = descriptions[0] if descriptions else base.description
    payload["categories"] = categories[:20]
    for field in ("subtitle", "publisher", "published_date", "language", "isbn10", "isbn13", "thumbnail", "cover_url", "preview_link", "info_link", "buy_link"):
        if not payload.get(field):
            payload[field] = next((getattr(b, field) for b in books if getattr(b, field)), "")
    if not payload.get("page_count"):
        payload["page_count"] = next((b.page_count for b in books if b.page_count), None)
    if payload.get("average_rating") is None:
        payload["average_rating"] = next((b.average_rating for b in books if b.average_rating is not None), None)
    payload["ratings_count"] = max((b.ratings_count for b in books), default=0)
    return Book.from_dict(payload)


def deduplicate_books(books: list[Book]) -> list[Book]:
    """Merge duplicate catalogue records instead of discarding useful metadata.

    Google Books often has the synopsis and rating while Open Library has stronger
    subjects, covers or edition data.  Older builds selected only one provider's
    record, which made descriptions appear to vanish.  Matching title/author
    records are now merged so the result keeps the richest fields from both.
    """
    def norm_title(value: str) -> str:
        value = re.sub(
            r"\b(a novel|the complete serial novel|stories|a memoir|a novella)\b",
            "",
            value,
            flags=re.I,
        )
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    def norm_author(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    grouped: dict[str, list[Book]] = {}
    order: list[str] = []
    for book in books:
        title = norm_title(book.title)
        author = norm_author(book.author_text)
        isbn = re.sub(r"\D", "", book.primary_isbn)
        # Prefer work-level identity so different editions/ISBNs from both
        # catalogues can contribute metadata to one visible result.
        key = f"{title}|{author}" if title and author else isbn or title
        if not key:
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(book)

    return [merge_book_records(grouped[key]) for key in order]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
