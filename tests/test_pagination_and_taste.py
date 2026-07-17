from bookverse.api_clients import BookSearchService
from bookverse.models import Book
from bookverse.personalization import build_taste_seed, taste_fingerprint


class _Google:
    enabled = True

    def __init__(self) -> None:
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return [Book(source="google", source_id=f"g{kwargs['start_index']}", title="Google")]


class _OpenLibrary:
    def __init__(self) -> None:
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return [Book(source="openlibrary", source_id=f"o{kwargs['page']}", title="Open")]


def test_search_page_is_forwarded_to_both_catalogues() -> None:
    service = BookSearchService("key", "reader@example.com")
    google = _Google()
    openlibrary = _OpenLibrary()
    service.google = google
    service.openlibrary = openlibrary

    response = service.search("horror", max_results=24, page_index=2)
    assert len(response.books) == 2
    assert google.calls[0]["start_index"] == 40
    assert openlibrary.calls[0]["page"] == 3


def test_taste_seed_uses_profile_and_positive_library_signals() -> None:
    profile = {
        "id": 1,
        "updated_at": "now",
        "favourite_niches": ["Extreme horror"],
        "top_books": ["The Shining"],
    }
    liked = Book(
        source="test",
        source_id="1",
        title="Liked",
        categories=("Psychological horror", "Survival"),
        description="A disturbing psychological horror story.",
    )
    entries = [
        {
            "uid": liked.uid,
            "book": liked,
            "shelf": "Favourites",
            "user_rating": 5.0,
            "updated_at": "now",
        }
    ]
    seed = build_taste_seed(profile, entries)
    assert "Extreme horror" in seed.categories
    assert "Psychological horror" in seed.categories
    assert "The Shining" in seed.description
    assert taste_fingerprint(profile, entries)
