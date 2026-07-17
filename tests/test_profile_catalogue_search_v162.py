from pathlib import Path


def test_profile_picker_uses_both_catalogues_without_language_filter():
    source = (Path(__file__).parents[1] / "bookverse" / "views.py").read_text()
    start = source.index('with st.form("profile_book_search_form"')
    end = source.index('selected_payloads = list', start)
    section = source[start:end]
    assert '"Both"' in section
    assert '"",\n                            "relevance"' in section
    assert 'combined_payloads[:36]' in section


def test_open_library_maps_english_language_code():
    source = (Path(__file__).parents[1] / "bookverse" / "api_clients.py").read_text()
    assert '"eng" if language.casefold() in {"en", "english"}' in source
