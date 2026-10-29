from app.pipeline import process_websites

test_urls = [
    "https://olympicfruit.com/",
    "https://freshdiamond.nl/",
]

results = process_websites(test_urls)

for result in results:
    print("\n" + "=" * 60)
    print("Company:", result.get("company_name", "Unknown"))
    print("Website:", result.get("website", result.get("source_url", "")))
    print("Email:", result.get("email") or "Not found")
    print("Products:", result.get("products", []))
    print("Score:", result.get("score", "N/A"))

    if result.get("error"):
        print("Processing error:", result["error"])

    qualification = result.get("ai_qualification")
    if qualification:
        print("AI qualification:", qualification)
    elif result.get("ai_qualification_error"):
        print("AI error:", result["ai_qualification_error"])
    else:
        print("AI qualification: Not returned")
