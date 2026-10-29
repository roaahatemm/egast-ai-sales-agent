from app.scoring import score_lead


def test_score_lead_returns_valid_score():
    lead = {
        "company_name": "Example Importer",
        "country": "Germany",
        "industry": "Fresh Produce Import",
        "website": "https://example.com",
        "email": "contact@example.com",
        "products": ["Fresh fruit", "Vegetables"],
    }

    score = score_lead(lead)

    assert isinstance(score, (int, float))
    assert 0 <= score <= 100


def test_score_lead_returns_zero_for_empty_lead():
    score = score_lead({})

    assert score == 0
