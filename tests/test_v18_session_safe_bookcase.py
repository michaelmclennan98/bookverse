from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (ROOT / "bookverse" / "views.py").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    start = VIEWS.index(f"def {name}(")
    candidates = [
        position for position in (
            VIEWS.find("\ndef ", start + 1),
            VIEWS.find("\n@st.dialog", start + 1),
        ) if position != -1
    ]
    end = min(candidates) if candidates else len(VIEWS)
    return VIEWS[start:end]


def test_bookcase_uses_callbacks_not_query_string_navigation() -> None:
    library = _function_source("render_library")
    assert "st.button(" in library
    assert "library_selected_uid" in library
    assert "href=\"?library_book=" not in library
    assert "st.query_params" not in library


def test_book_dialog_closes_without_url_navigation() -> None:
    dialog = _function_source("render_bookcase_book_dialog")
    assert 'st.session_state.pop("library_selected_uid", None)' in dialog
    assert "st.query_params" not in dialog
    assert "_render_internal_book_information(book)" in dialog
