from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (ROOT / "bookverse" / "views.py").read_text(encoding="utf-8")
CACHE = (ROOT / "bookverse" / "cache.py").read_text(encoding="utf-8")


def _function_source(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    candidates = [
        pos for pos in (source.find("\ndef ", start + 1), source.find("\n@st.dialog", start + 1))
        if pos != -1
    ]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def test_search_cards_show_description_without_opening_details() -> None:
    card = _function_source(VIEWS, "render_book_card")
    assert 'st.markdown("**Description**")' in card
    assert "_description_preview(book.description, 650)" in card
    assert 'with st.expander("Read the full description")' in card


def test_details_button_hydrates_exact_catalogue_record() -> None:
    card = _function_source(VIEWS, "render_book_card")
    assert "cached_enrich_catalogue_book(" in card
    assert "st.session_state.catalogue_detail_book = enriched_payload" in card
    assert "Loading full book details" in card


def test_catalogue_hydration_uses_exact_seed_enrichment_and_safe_fallback() -> None:
    function = _function_source(CACHE, "cached_enrich_catalogue_book")
    assert "service.enrich_seed(book)" in function
    assert "return book.to_dict()" in function
