from bookverse.models import Book


def test_google_book_parser() -> None:
    item = {
        "id": "abc123",
        "volumeInfo": {
            "title": "Example Book",
            "authors": ["A. Writer"],
            "description": "<b>A story</b> about testing.",
            "categories": ["Fantasy"],
            "publishedDate": "2025-03-01",
            "pageCount": 320,
            "averageRating": 4.2,
            "ratingsCount": 99,
            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780000000001"}],
            "imageLinks": {"thumbnail": "http://example.com/cover.jpg"},
        },
        "saleInfo": {"isEbook": True},
        "accessInfo": {"epub": {"isAvailable": True}},
    }
    book = Book.from_google(item)
    assert book.uid == "google:abc123"
    assert book.title == "Example Book"
    assert book.description == "A story about testing."
    assert book.published_year == 2025
    assert book.cover_url.startswith("https://")
    assert book.ebook_available is True


def test_openlibrary_parser() -> None:
    doc = {
        "key": "/works/OL1W",
        "title": "Open Example",
        "author_name": ["Writer One"],
        "first_publish_year": 1999,
        "subject": ["Mystery", "Detective fiction"],
        "isbn": ["1234567890", "9781234567897"],
        "cover_i": 42,
        "ratings_average": 4.0,
        "ratings_count": 50,
    }
    book = Book.from_openlibrary(doc)
    assert book.uid == "openlibrary:OL1W"
    assert book.isbn13 == "9781234567897"
    assert book.published_year == 1999
    assert "covers.openlibrary.org" in book.best_cover


def test_clean_text_flattens_stringified_list() -> None:
    from bookverse.models import clean_text
    assert clean_text("['Me está viendo']") == "Me está viendo"
