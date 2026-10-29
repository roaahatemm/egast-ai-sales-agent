
from app.discovery import build_search_queries


def test_build_search_queries():
    profile = {
        "products": [
            {
                "name": "Fresh Oranges",
                "varieties": ["Valencia", "Navel"],
                "available": True,
            },
            {
                "name": "Fresh Grapes",
                "varieties": ["Red Seedless"],
                "available": True,
            },
        ],
        "target_countries": ["Germany", "Netherlands"],
    }

    queries = build_search_queries(profile)

    # The expanded discovery strategy should generate many queries.
    assert len(queries) > 12

    # Queries should be unique.
    assert len(queries) == len(set(queries))

    # Both target countries should be covered.
    assert any("Germany" in query for query in queries)
    assert any("Netherlands" in query for query in queries)

    # Buyer categories and both products should be included.
    assert any("supermarket" in query.lower() for query in queries)
    assert any("Fresh Oranges" in query for query in queries)
    assert any("Fresh Grapes" in query for query in queries)


def test_unavailable_products_are_skipped():
    profile = {
        "products": [
            {"name": "Fresh Grapes", "available": False}
        ],
        "target_countries": ["Germany"],
    }

    assert build_search_queries(profile) == []
