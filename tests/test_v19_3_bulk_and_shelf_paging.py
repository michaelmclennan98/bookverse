from pathlib import Path


def test_personalised_checkbox_and_bulk_keys_share_scope():
    source = (Path(__file__).parents[1] / "bookverse" / "views.py").read_text()
    assert "selection_scope = _personalised_selection_scope(key_prefix)" in source
    assert 'key=f"select_{selection_scope}_{book.uid}"' in source
    assert 'st.session_state.get(f"select_{selection_scope}_{book.uid}", False)' in source


def test_bulk_action_bar_is_always_rendered():
    source = (Path(__file__).parents[1] / "bookverse" / "views.py").read_text()
    assert 'st.markdown("#### Selected-book actions")' in source
    assert '"Add selected to Want to Read"' in source
    assert '"Mark selected as Read"' in source
    assert 'disabled=not has_selection' in source


def test_bookcase_uses_fifteen_book_pages():
    source = (Path(__file__).parents[1] / "bookverse" / "views.py").read_text()
    assert "page_size = 15" in source
    assert '"← Previous 15"' in source
    assert '"Next 15 →"' in source
    assert "columns = st.columns(page_size" in source
