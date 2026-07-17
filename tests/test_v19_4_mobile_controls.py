from pathlib import Path


VIEWS_PATH = Path(__file__).parents[1] / "bookverse" / "views.py"


def test_phone_controls_are_persistent_and_staged():
    source = VIEWS_PATH.read_text(encoding="utf-8")
    assert 'key="show_phone_controls"' in source
    assert 'key="mobile_page_selector"' in source
    assert 'key="mobile_go_button"' in source
    assert 'st.session_state.phone_active_page = page' in source
    assert 'Selecting an option does not navigate by itself' in source


def test_phone_controls_preserve_session_and_hide_inaccessible_sidebar_on_mobile():
    source = VIEWS_PATH.read_text(encoding="utf-8")
    assert '@media (max-width: 768px)' in source
    assert '[data-testid="stSidebar"]' in source
    assert '_set_active_page(staged_page)' in source
    assert 'st.session_state.active_page = page' in source
    assert 'top: calc(3.75rem + env(safe-area-inset-top))' in source
    assert 'margin: 3.6rem 0 .7rem' in source
    assert 'env(safe-area-inset-bottom)' in source
