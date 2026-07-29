from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from bookverse import cache
from bookverse.models import Book


def _book(**overrides) -> Book:
    payload = {
        "source": "openlibrary",
        "source_id": "OL1W",
        "title": "The Night House",
        "authors": ("Example Author",),
        "description": "",
        "categories": ("Horror", "Psychological fiction"),
        "language": "",
    }
    payload.update(overrides)
    return Book(**payload)


def test_missing_description_is_deferred_for_metadata_repair() -> None:
    book = _book()
    rules = {"require_description": True, "english_only": True}
    rejections = cache._non_repairable_rule_rejections(book, rules)
    assert "missing a useful description" not in rejections
    assert "not confirmed as English" not in rejections


def test_nonrepairable_textbook_rule_still_blocks_candidate() -> None:
    book = _book(
        title="English Grammar Workbook",
        categories=("English language", "Grammar", "Problems, exercises"),
    )
    rejections = cache._non_repairable_rule_rejections(
        book,
        {"exclude_textbooks": True, "exclude_reference": True},
    )
    assert rejections


def test_exact_google_repair_merges_description(monkeypatch, tmp_path) -> None:
    sparse = _book()
    repaired = _book(
        source="google",
        source_id="google-1",
        description=(
            "A psychological horror novel about a family trapped in an isolated house "
            "while a violent secret closes in around them."
        ),
        language="en",
    )

    class FakeGoogle:
        enabled = True

    class FakeOpenLibrary:
        def enrich_work(self, book: Book) -> Book:
            return book

    class FakeService:
        google = FakeGoogle()
        openlibrary = FakeOpenLibrary()

        def search(self, **kwargs):
            if kwargs.get("provider") == "Google Books":
                return SimpleNamespace(books=[repaired], provider_messages=[])
            return SimpleNamespace(books=[], provider_messages=[])

    monkeypatch.setattr(cache, "get_cached", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cache, "set_cached", lambda *_args, **_kwargs: None)

    result = cache._repair_recommendation_candidate(
        sparse,
        FakeService(),  # type: ignore[arg-type]
        str(tmp_path / "cache.sqlite3"),
    )
    assert result.description == repaired.description
    assert result.language == "en"


def test_failed_personalised_results_are_not_persisted() -> None:
    import inspect

    signature = inspect.signature(cache.cached_personalised)
    assert "attempt_token" in signature.parameters
    source = Path(cache.__file__).read_text(encoding="utf-8")
    assert "if payloads:" in source
    assert 'set_cached(' in source
