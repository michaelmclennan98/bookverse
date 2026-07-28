from pathlib import Path


VIEWS_PATH = Path(__file__).parents[1] / "bookverse" / "views.py"


def test_website_top_navigation_replaces_hidden_phone_menu():
    source = VIEWS_PATH.read_text(encoding="utf-8")
    assert 'key="top_navigation"' in source
    assert 'key="top_nav_links"' in source
    assert 'top_navigation_{page_name}' in source
    assert 'key="show_phone_controls"' not in source
    assert 'key="mobile_go_button"' not in source


def test_top_navigation_is_responsive_and_sidebar_is_hidden():
    source = VIEWS_PATH.read_text(encoding="utf-8")
    assert '@media (max-width: 768px)' in source
    assert '[data-testid="stSidebar"]' in source
    assert '.st-key-top_navigation' in source
    assert '.st-key-top_nav_links' in source
    assert 'st.session_state.active_page = page' in source
    assert 'env(safe-area-inset-bottom)' in source
