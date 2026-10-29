import sqlite3
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from app.discovery import discover_leads, normalize_domain
from app.directory_crawler import is_safe_public_url
from app.pipeline import process_website
from app.database import DATABASE_PATH


MAX_WEBSITES = 20
MAX_QUERIES = 3
RESULTS_PER_QUERY = 10

def main():
    print("=" * 60)
    print("EGAST AI SALES AGENT - CONTROLLED PILOT")
    print("=" * 60)
    print("Maximum websites:", MAX_WEBSITES)
    print("Existing leads will be skipped.")
    print("Email sending and Gmail drafts are disabled.")

    # Read existing websites without changing the database.
    db_uri = Path(DATABASE_PATH).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        rows = conn.execute(
            "SELECT website FROM leads WHERE website IS NOT NULL"
        ).fetchall()

    existing_domains = {
        normalize_domain(row[0]) for row in rows if row[0]
    }

    print("Existing website domains:", len(existing_domains))

    # Discover candidates. Search caching remains enabled.
    results = discover_leads(
        max_queries=MAX_QUERIES,
        results_per_query=RESULTS_PER_QUERY,
    )

    candidates = []
    seen_domains = set()
    skipped_existing = 0
    skipped_directory = 0
    skipped_unsafe = 0

    for result in results:
        url = (result.get("url") or "").strip()
        domain = normalize_domain(url)

        if not url or not domain or domain in seen_domains:
            continue

        seen_domains.add(domain)
        host = (urlsplit(url).hostname or "").lower()

        # Skip directory/search pages rather than individual companies.
        if any(term in host for term in (
            "europages.", "linkedin.com", "facebook.com",
            "instagram.com", "yellowpages."
        )):
            skipped_directory += 1
            continue

        if domain in existing_domains:
            skipped_existing += 1
            continue

        try:
            if not is_safe_public_url(url):
                skipped_unsafe += 1
                print("Skipped unsafe URL:", url)
                continue
        except Exception as exc:
            skipped_unsafe += 1
            print("Safety check failed:", url, "-", exc)
            continue

        candidates.append(result)

        if len(candidates) >= MAX_WEBSITES:
            break

    print("\nCandidates selected:", len(candidates))
    print("Skipped existing domains:", skipped_existing)
    print("Skipped directory pages:", skipped_directory)
    print("Skipped unsafe URLs:", skipped_unsafe)

    if not candidates:
        print("No new safe candidates available. Nothing processed.")
        return

    print("\nSelected websites:")
    for index, item in enumerate(candidates, 1):
        print(f"{index}. {item['url']}")

    input(
        "\nReview the list above. Press ENTER to start processing, "
        "or Ctrl+C to cancel: "
    )

    started = perf_counter()
    processed = 0
    failed = 0
    qualified = 0
    statuses = {
        "potential_buyer": 0,
        "not_buyer": 0,
        "uncertain": 0,
        "ai_error": 0,
    }

    for index, item in enumerate(candidates, 1):
        url = item["url"]
        print(f"\n[{index}/{len(candidates)}] {url}")

        try:
            lead = process_website(url)

            if lead.get("error"):
                failed += 1
                print("Website processing failed:", lead["error"])
                continue

            processed += 1
            print("Company:", lead.get("company_name") or "Unknown")
            print("Database ID:", lead.get("id"))

            qualification = lead.get("ai_qualification")
            if qualification:
                qualified += 1
                status = qualification.get("buyer_status", "ai_error")
                if status not in statuses:
                    status = "ai_error"
                statuses[status] += 1
                print("Buyer status:", status)
                print("Buyer type:", qualification.get("buyer_type"))
                print("Confidence:", qualification.get("confidence"))
                print("Next action:",
                      qualification.get("recommended_next_action"))
            else:
                statuses["ai_error"] += 1
                print("AI qualification error:",
                      lead.get("ai_qualification_error", "No result"))

        except Exception as exc:
            failed += 1
            print("Processing error:", type(exc).__name__, exc)

    elapsed = perf_counter() - started

    print("\n" + "=" * 60)
    print("PILOT SUMMARY")
    print("=" * 60)
    print("Candidates selected:", len(candidates))
    print("Websites processed:", processed)
    print("Website failures:", failed)
    print("AI qualifications returned:", qualified)
    print("Potential buyers:", statuses["potential_buyer"])
    print("Not buyers:", statuses["not_buyer"])
    print("Uncertain:", statuses["uncertain"])
    print("AI errors:", statuses["ai_error"])
    print(f"Total processing time: {elapsed:.1f} seconds")
    print("Database:", DATABASE_PATH)
    print("No email sending or Gmail draft creation performed.")

if __name__ == "__main__":
    main()
