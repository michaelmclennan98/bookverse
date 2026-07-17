from bookverse.api_clients import deduplicate_books
from bookverse.models import Book
from bookverse.personalization import taste_summary


def test_duplicate_catalogue_records_are_merged_not_replaced() -> None:
    google = Book(
        source="google",
        source_id="g1",
        title="Example Book",
        authors=("A Writer",),
        description="A complete synopsis supplied by Google Books.",
        average_rating=4.4,
        ratings_count=240,
        language="en",
    )
    openlibrary = Book(
        source="openlibrary",
        source_id="ol1",
        title="Example Book",
        authors=("A Writer",),
        categories=("Psychological thriller", "Mystery"),
        cover_url="https://covers.openlibrary.org/b/id/1-L.jpg",
        language="en",
    )

    results = deduplicate_books([google, openlibrary])

    assert len(results) == 1
    assert results[0].description == google.description
    assert "Psychological thriller" in results[0].categories
    assert results[0].best_cover
    assert results[0].average_rating == 4.4


def test_taste_summary_removes_catalogue_noise() -> None:
    book = Book(
        source="openlibrary",
        source_id="ol2",
        title="A Horror Novel",
        authors=("A Writer",),
        description="A dark horror story.",
        categories=("Horror", "New York Times bestseller", "Open Library Staff Picks"),
        language="en",
    )
    entries = [{"uid": book.uid, "book": book, "shelf": "Finished", "user_rating": 5.0, "updated_at": "2026-07-16T00:00:00"}]

    summary = taste_summary({"favourite_niches": [], "top_books": []}, entries, 8)

    assert "Horror" in summary
    assert all("new york times" not in value.casefold() for value in summary)
    assert all("open library" not in value.casefold() for value in summary)
