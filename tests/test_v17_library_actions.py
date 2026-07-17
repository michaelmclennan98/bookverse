from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS_PATH = ROOT / "bookverse" / "views.py"
CACHE_PATH = ROOT / "bookverse" / "cache.py"


def _function_source(name: str) -> str:
    source = VIEWS_PATH.read_text(encoding="utf-8")
    start = source.index(f"def {name}(")
    next_defs = [
        index for index in (
            source.find("\ndef ", start + 1),
            source.find("\n@st.dialog", start + 1),
        )
        if index != -1
    ]
    end = min(next_defs) if next_defs else len(source)
    return source[start:end]


def test_personalised_refresh_cycles_and_uses_live_refresh_token() -> None:
    source = _function_source("_render_personalised_section")
    assert "personalised_display_offset" in source
    assert "personalised_refresh_token" in source
    assert "refresh_token=refresh_token" in source
    assert "Refreshing only changes the suggestions — it never saves a book." in source


def test_all_catalogue_cards_have_explicit_read_actions() -> None:
    source = _function_source("render_book_card")
    assert '"Want to Read"' in source
    assert '"✓ Mark as Read"' in source
    assert 'db.save_entry(book, "Want to Read")' in source
    assert 'db.save_entry(book, "Finished"' in source


def test_render_book_card_toasts_only_live_inside_button_branches() -> None:
    module = ast.parse(VIEWS_PATH.read_text(encoding="utf-8"))
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_book_card"
    )
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(function):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    toast_calls = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "st" and node.func.attr == "toast":
            toast_calls.append(node)

    assert toast_calls
    for call in toast_calls:
        current = parents.get(call)
        assert any(
            isinstance(ancestor, ast.If)
            for ancestor in _ancestors(current, parents)
        ), "A toast must not run merely because a card was rendered."


def _ancestors(node: ast.AST | None, parents: dict[ast.AST, ast.AST]):
    while node is not None:
        yield node
        node = parents.get(node)


def test_bookcase_stays_in_same_tab_and_uses_internal_details() -> None:
    source = VIEWS_PATH.read_text(encoding="utf-8")
    dialog = _function_source("render_bookcase_book_dialog")
    assert "library_selected_uid" in source
    assert 'href="?library_book=' not in source
    assert "_render_internal_book_information(book)" in dialog
    assert "link_button(" not in dialog
    assert "Genres and subjects" in source
    assert "ISBN-13" in source


def test_cached_personalised_refresh_token_changes_query_and_order() -> None:
    source = CACHE_PATH.read_text(encoding="utf-8")
    assert "refresh_token: int = 0" in source
    assert "page_index=refresh_token % 4" in source
    assert "shift = (refresh_token * 6) % len(ranked_records)" in source
