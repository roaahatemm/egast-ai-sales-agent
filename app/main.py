
from app.config import load_company_profile
from app.discovery import discover_leads
from app.pipeline import process_website
from app.database import initialize_database, get_all_leads


def main():
    print("=" * 60)
    print("EGAST AI SALES AGENT")
    print("=" * 60)

    # Step 1: Initialize the database.
    print("\n[1/4] Initializing database...")
    initialize_database()
    print("Database ready.")

    # Step 2: Load the company profile.
    print("\n[2/4] Loading EGAST company profile...")
    profile = load_company_profile()

    if not profile:
        print("ERROR: Could not load the EGAST company profile.")
        return

    print(f"Company: {profile.get('company_name', 'EGAST')}")

    # Step 3: Discover potential buyers.
    print("\n[3/4] Discovering potential buyers...")

    try:
        results = discover_leads()
    except Exception as error:
        print(f"Discovery failed: {error}")
        return

    if not results:
        print("No potential buyers found.")
        print("Check that Docker/OpenSERP is running.")
        return

    print(f"Discovered {len(results)} search results.")

    # Step 4: Process each discovered website.
    print("\n[4/4] Processing websites...")

    processed = 0
    failed = 0

    for index, result in enumerate(results, start=1):
        url = result.get("url", "").strip()

        if not url:
            failed += 1
            print(f"[{index}/{len(results)}] Skipped: missing URL.")
            continue

        print(f"\n[{index}/{len(results)}] Processing: {url}")

        try:
            lead = process_website(url)

            if lead.get("error"):
                failed += 1
                print(f"Failed: {lead['error']}")
                continue

            processed += 1
            print(f"Company: {lead.get('company_name', 'Unknown')}")
            print(f"Country: {lead.get('country') or 'Not detected'}")
            print(f"Industry: {lead.get('industry') or 'Not detected'}")
            print(f"Email: {lead.get('email') or 'Not found'}")
            print(f"Score: {lead.get('score', 0)}")
            print(f"Database ID: {lead.get('id')}")

        except Exception as error:
            failed += 1
            print(f"Failed to process website: {error}")

    # Print the final database summary.
    saved_leads = get_all_leads()

    print("\n" + "=" * 60)
    print("RUN SUMMARY")
    print("=" * 60)
    print(f"Search results discovered: {len(results)}")
    print(f"Websites processed: {processed}")
    print(f"Failed or skipped: {failed}")
    print(f"Total leads in database: {len(saved_leads)}")
    print("\nRun completed.")


if __name__ == "__main__":
    main()
