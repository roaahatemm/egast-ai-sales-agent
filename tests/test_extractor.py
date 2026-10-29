
from app.extractor import extract_lead


def test_extract_lead_from_html():
    html = """
    <html>
        <head>
            <title>Example Importer | Fresh Produce</title>
        </head>
        <body>
            <p>Contact us at buyer@example.com</p>
            <a href="mailto:sales@example.com">Email sales</a>
        </body>
    </html>
    """

    lead = extract_lead(html, "https://example.com/about")

    assert lead["company_name"] == "Example Importer"
    assert lead["website"] == "https://example.com"
    assert "buyer@example.com" in lead["emails"]
    assert "sales@example.com" in lead["emails"]
    assert lead["source_url"] == "https://example.com/about"
