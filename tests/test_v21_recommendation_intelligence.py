from __future__ import annotations

from bookverse.api_clients import RequestBudget
from bookverse.database import LibraryDatabase
from bookverse.models import Book
from bookverse.recommendation_intelligence import (
    DEFAULT_RULES,
    book_dna,
    filter_recommendation_payloads,
    normalise_rules,
    rule_rejections,
    select_diverse_records,
)


def _book(
    source_id: str,
    title: str,
    author: str,
    *,
    description: str = "A substantial adult novel description with enough detail to classify the story.",
    categories: tuple[str, ...] = ("Fiction", "Thriller"),
    page_count: int = 320,
) -> Book:
    return Book(
        source="test",
        source_id=source_id,
        title=title,
        authors=(author,),
        description=description,
        categories=categories,
        language="en",
        page_count=page_count,
        published_date="2024",
        average_rating=4.2,
        ratings_count=250,
    )


def test_rules_are_bounded_and_defaults_are_preserved() -> None:
    rules = normalise_rules(
        {
            "diversity": 900,
            "minimum_public_rating": 9,
            "maximum_per_author": 0,
            "require_description": False,
        }
    )
    assert rules["diversity"] == 100
    assert rules["minimum_public_rating"] == 5.0
    assert rules["maximum_per_author"] == 1
    assert rules["require_description"] is False
    assert rules["exclude_textbooks"] is DEFAULT_RULES["exclude_textbooks"]


def test_hard_rules_reject_textbooks_and_missing_descriptions() -> None:
    textbook = _book(
        "grammar",
        "English Grammar and Composition",
        "J. Teacher",
        categories=("English language", "Grammar", "Textbook", "Problems, exercises"),
    )
    reasons = rule_rejections(textbook, DEFAULT_RULES)
    assert any("textbook" in reason for reason in reasons)

    sparse = _book("sparse", "Sparse Book", "A. Writer", description="")
    reasons = rule_rejections(sparse, DEFAULT_RULES)
    assert "missing a useful description" in reasons

    allowed = normalise_rules({**DEFAULT_RULES, "exclude_textbooks": False, "require_description": False})
    assert not rule_rejections(textbook, allowed)



def test_saved_recommendations_are_refiltered_when_rules_change() -> None:
    valid = _book("valid", "Valid Horror", "A. Writer")
    missing_description = _book("missing", "Missing", "B. Writer", description="")
    textbook = _book(
        "textbook-old",
        "English Grammar and Composition",
        "J. Teacher",
        categories=("English language", "Grammar", "Textbook"),
    )
    payloads = [
        {"book": valid.to_dict(), "match_percent": 80},
        {"book": missing_description.to_dict(), "match_percent": 80},
        {"book": textbook.to_dict(), "match_percent": 80},
    ]
    filtered, hidden = filter_recommendation_payloads(payloads, DEFAULT_RULES)
    assert hidden == 2
    assert [item["book"]["source_id"] for item in filtered] == ["valid"]

def test_book_dna_extracts_intensity_romance_and_pace() -> None:
    book = _book(
        "dark-romance",
        "The Captive Night",
        "A. Author",
        description=(
            "A dark, violent and suspenseful adult romance with explicit content, "
            "captivity, revenge and a fast-paced fight to survive."
        ),
        categories=("Dark romance", "Psychological thriller", "Adult fiction"),
    )
    dna = book_dna(book)
    assert dna["intensity"] in {"Dark", "Extreme"}
    assert dna["romance"] in {"Medium", "High"}
    assert dna["pace"] == "Fast"


def test_diversity_selector_respects_author_cap() -> None:
    records = [
        {"book": _book("one", "One", "Same Author"), "rank_score": 100.0},
        {"book": _book("two", "Two", "Same Author"), "rank_score": 99.0},
        {"book": _book("three", "Three", "Different Author"), "rank_score": 80.0},
    ]
    selected, _stats = select_diverse_records(
        records,
        3,
        {**DEFAULT_RULES, "maximum_per_author": 1, "maximum_per_primary_genre": 10},
    )
    authors = [record["book"].author_text for record in selected]
    assert authors.count("Same Author") == 1
    assert "Different Author" in authors


def test_request_budget_is_thread_safe_and_strict() -> None:
    budget = RequestBudget(max_google=2, max_openlibrary=1)
    assert budget.claim("google")
    assert budget.claim("google")
    assert not budget.claim("google")
    assert budget.claim("openlibrary")
    assert not budget.claim("openlibrary")
    snapshot = budget.snapshot()
    assert snapshot["google_attempts"] == 2
    assert snapshot["google_denied"] == 1
    assert snapshot["openlibrary_attempts"] == 1
    assert snapshot["openlibrary_denied"] == 1


def test_feedback_memory_can_delete_one_or_all(tmp_path) -> None:
    db = LibraryDatabase(tmp_path / "v21.db")
    profile = db.create_profile("reader", "Reader", "1234")
    db.set_active_user(profile["id"])
    first = _book("first", "First", "Writer One")
    second = _book("second", "Second", "Writer Two")
    db.set_recommendation_feedback(first, "Not interested")
    db.set_recommendation_feedback(second, "Too long")

    db.delete_recommendation_feedback(first.uid)
    feedback = db.list_recommendation_feedback()
    assert len(feedback) == 1
    assert feedback[0]["uid"] == second.uid

    assert db.clear_recommendation_feedback() == 1
    assert db.list_recommendation_feedback() == []


def test_v21_ui_and_saved_state_are_wired() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    views = (root / "bookverse" / "views.py").read_text(encoding="utf-8")
    cache = (root / "bookverse" / "cache.py").read_text(encoding="utf-8")
    features = (root / "bookverse" / "feature_views.py").read_text(encoding="utf-8")
    assert "personalised_last_results_v21" in views
    assert "Latest scan report" in views
    assert "recommendation_payloads" in views
    assert "rules_payload=rules" in views
    assert "RequestBudget" in cache
    assert "recommendation-seed-pool" in cache
    assert "scan_report" in cache
    assert "render_recommendation_preferences" in features
    assert "Choose My Next Book" in features
    assert "Library health" in features
