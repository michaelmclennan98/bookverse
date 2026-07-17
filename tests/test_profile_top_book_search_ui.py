from pathlib import Path


VIEWS_PATH = Path(__file__).resolve().parents[1] / "bookverse" / "views.py"


def _profile_gate_source() -> str:
    source = VIEWS_PATH.read_text(encoding="utf-8")
    start = source.index("def render_profile_gate")
    end = source.index("\n\ndef render_sidebar", start)
    return source[start:end]


def test_top_book_search_uses_submit_form_and_enter_key() -> None:
    source = _profile_gate_source()
    assert 'with st.form("profile_book_search_form"' in source
    assert 'st.form_submit_button(' in source
    assert '"Search book catalogue"' in source
    assert 'search_col.button("Search"' not in source


def test_top_book_search_has_keyword_fallback_and_exact_selection() -> None:
    source = _profile_gate_source()
    assert '"Title"' in source
    assert '"Keyword"' in source
    assert 'Choose the exact book' in source
    assert 'Add selected book to my top books' in source
