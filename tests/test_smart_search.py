from bookverse.smart_search import parse_smart_query


def test_smart_query_extracts_constraints() -> None:
    plan = parse_smart_query(
        "I want fantasy with dragons and enemies to lovers under 500 pages after 2018 without horror"
    )
    assert "fantasy" in plan.genres
    assert "dragons" in plan.tropes
    assert "enemies to lovers" in plan.tropes
    assert plan.max_pages == 500
    assert plan.year_from == 2018
    assert "horror" in plan.negative_terms


def test_smart_query_extracts_similar_title() -> None:
    plan = parse_smart_query("Something like Harry Potter but darker")
    assert plan.similar_to == "Harry Potter"
    assert "Harry Potter" in plan.api_query
