
from app.ai_qualifier import qualify_lead




sample_lead = {
    "company_name": "Example Produce Trading GmbH",
    "website": "https://example.com",
    "source_url": "https://example.com",
    "description": (
        "The supplied test description says this company imports "
        "fresh oranges and distributes them to wholesale customers."
    ),
    "country": "Germany",
    "industry": "Fresh Produce Importer",
    "products": ["oranges"],
}



try:
    print("\nInput sent to AI:")
    print(sample_lead)
    result = qualify_lead(sample_lead)
    print("\nAI qualification result:")
    for key, value in result.items():
        print(f"{key}: {value}")
except Exception as exc:
    print(f"AI test failed: {type(exc).__name__}: {exc}")
