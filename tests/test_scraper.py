
from unittest.mock import Mock, patch

import pytest

from app.scraper import scrape_page


def test_scrape_page_extracts_links():
    html = """
    <html>
        <body>
            <a href="/products">Fresh Produce</a>
            <a href="https://example.com">Example</a>
            <a href="/products">Duplicate</a>
            <a href="mailto:test@example.com">Email</a>
        </body>
    </html>
    """

    response = Mock()
    response.text = html
    response.raise_for_status.return_value = None

    with patch("app.scraper.requests.get", return_value=response):
        results = scrape_page("https://example.com")

    assert len(results) == 2
    assert results[0]["title"] == "Fresh Produce"
    assert results[0]["url"] == "https://example.com/products"
    assert results[0]["domain"] == "example.com"


def test_scrape_page_rejects_invalid_scheme():
    with pytest.raises(ValueError):
        scrape_page("file:///etc/passwd")
