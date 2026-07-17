from __future__ import annotations

from pathlib import Path


VIEWS_PATH = Path(__file__).resolve().parents[1] / "bookverse" / "views.py"


def _dialog_source() -> str:
    source = VIEWS_PATH.read_text(encoding="utf-8")
    start = source.index('@st.dialog("Recommended books", width="large")')
    end = source.index("\n\ndef render_library", start)
    return source[start:end]


def test_recommendation_save_is_form_isolated() -> None:
    source = _dialog_source()
    assert "recommendation_save_form_" in source
    assert "st.form_submit_button" in source
    assert 'st.button("Save this recommendation"' not in source
    assert "Navigation is intentionally separated from the save form" in source


def test_navigation_buttons_have_unique_keys() -> None:
    source = _dialog_source()
    assert "similar_previous_{seed.uid}_{index}" in source
    assert "similar_next_{seed.uid}_{index}" in source
