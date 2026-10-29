

from app.local_ai_qualifier import qualify_lead

sample_lead = {
    "company_name": "Example Produce Trading GmbH",
    "website": "https://example.com",
    "source_url": "https://example.com",
    "description": (
        "TEST VERSION 2: This supplied description says the company "
        "imports fresh oranges and distributes them to wholesalers."
    ),
    "country": "Germany",
    "industry": "Fresh Produce Importer",
    "products": ["oranges"],
}

print("\nINPUT ACTUALLY SENT TO QUALIFIER:")
print(sample_lead)

try:
    result = qualify_lead(sample_lead)

    print("\nAI qualification result:")
    for key, value in result.items():
        print(f"{key}: {value}")

except Exception as exc:
    print(f"AI test failed: {type(exc).__name__}: {exc}")
