
from time import perf_counter

from app.local_ai_qualifier import qualify_lead


sample_lead = {
    "company_name": "Example Fresh Imports",
    "website": "https://example.com",
    "source_url": "https://example.com",
    "description": (
        "We import fresh oranges and grapes from international "
        "suppliers for wholesale distribution."
    ),
    "industry": "Fresh Produce Importer/Wholesaler",
    "products": ["oranges", "grapes"],
    "country": "Netherlands",
}

print("Benchmarking local AI qualification...")
print("Model: qwen2.5:3b")
print("This test does not save anything to the database.")

start = perf_counter()

try:
    result = qualify_lead(sample_lead)
    elapsed = perf_counter() - start

    print(f"\nElapsed time: {elapsed:.2f} seconds")
    print(f"Buyer status: {result['buyer_status']}")
    print(f"Buyer type: {result['buyer_type']}")
    print(f"Confidence: {result['confidence']}")
    print(f"Recommended action: {result['recommended_next_action']}")

except Exception as exc:
    elapsed = perf_counter() - start
    print(f"\nBenchmark failed after {elapsed:.2f} seconds")
    print(f"Error: {type(exc).__name__}: {exc}")

