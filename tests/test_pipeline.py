
from unittest.mock import patch

from app.pipeline import process_website, process_websites



def test_process_website():
    with (
        patch(
            "app.pipeline.scrape_page_with_html",
            return_value=(
                "<html><title>Example Importer</title></html>",
                [],
            ),
        ),
        patch("app.pipeline.extract_lead") as mock_extract,
        patch("app.pipeline.score_lead", return_value=75) as mock_score,
        patch("app.pipeline.save_lead", return_value=123),
        patch(
            "app.pipeline.qualify_lead",
            return_value={
                "buyer_status": "potential_buyer",
                "confidence": 80,
            },
        ),
        patch("app.pipeline.save_ai_qualification"),
    ):
        mock_extract.return_value = {
            "company_name": "Example Importer",
            "website": "https://example.com",
            "email": "buyer@example.com",
            "products": ["Fresh Oranges"],
        }

        lead = process_website("https://example.com")

        assert lead["company_name"] == "Example Importer"
        assert lead["score"] == 75
        assert lead["id"] == 123
        mock_score.assert_called_once()


def test_process_websites_returns_one_result_per_url():
    with patch(
        "app.pipeline.process_website",
        side_effect=[
            {"company_name": "Importer A", "score": 75},
            {"company_name": "Importer B", "score": 60},
        ],
    ):
        leads = process_websites([
            "https://a.example",
            "https://b.example",
        ])

    assert len(leads) == 2
    assert leads[0]["score"] == 75
    assert leads[1]["score"] == 60
