import sys
from types import SimpleNamespace


class _FakeCacheData:
    def __call__(self, *args, **kwargs):
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return lambda function: function

    def clear(self):
        return None


sys.modules.setdefault("streamlit", SimpleNamespace(cache_data=_FakeCacheData()))

from bookverse import cache
from bookverse.models import Book
from bookverse.recommender import RecommendationResult


def test_personalised_search_uses_exact_saved_book_seed(monkeypatch):
    seed = Book(
        source="google",
        source_id="playground",
        title="Playground",
        authors=("Aron Beauregard",),
        description="An adult extreme horror novel.",
        categories=("Extreme horror", "Splatterpunk"),
        language="en",
    )
    candidate = Book(
        source="google",
        source_id="other-horror",
        title="Another Extreme Horror",
        authors=("Different Author",),
        description="A graphic adult horror novel.",
        categories=("Extreme horror",),
        language="en",
    )
    seen_titles = []

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def prepare_recommendation_seed(self, book):
            seen_titles.append(book.title)
            return book

        def recommendation_candidates(self, _seed, max_results=110):
            return SimpleNamespace(books=[candidate], provider_messages=[])

        def enrich_recommendation_candidates(self, _seed, candidates, limit=8):
            return candidates

        def search(self, **_kwargs):
            return SimpleNamespace(books=[], provider_messages=[])

    monkeypatch.setattr(cache, "BookSearchService", FakeService)
    monkeypatch.setattr(
        cache,
        "rank_similar_detailed",
        lambda _seed, _candidates, limit=10: [
            RecommendationResult(
                book=candidate,
                score=0.72,
                reasons=("extreme horror",),
                match_percent=88,
                match_label="Strong match",
            )
        ],
    )

    function = getattr(cache.cached_personalised, "__wrapped__", cache.cached_personalised)
    results, messages = function(
        {"top_books": ["Playground — Aron Beauregard"], "favourite_niches": []},
        [{"book": seed.to_dict(), "shelf": "Finished", "user_rating": None}],
        "key",
        "email@example.com",
        5,
        18,
        "test-version",
    )

    assert messages == []
    assert seen_titles == ["Playground"]
    assert results[0]["book"]["title"] == "Another Extreme Horror"
    assert "because you liked Playground" in results[0]["reasons"]


def test_for_you_no_longer_requires_three_saved_books():
    source = open("bookverse/views.py", encoding="utf-8").read()
    assert 'if len(entries) < 3:' not in source
    assert 'if not entries:' in source
    assert 'cached_personalised(' in source
