
from app.discovery import discover_leads
from app.pipeline import process_website


def run_discovery_pipeline() -> None:
    """Discover candidate websites and process each one."""

    results = discover_leads()

    if not results:
        print("No relevant search results were discovered.")
        return

    print(f"\nDiscovered {len(results)} candidate websites.")

    processed = 0
    failed = 0

    for index, result in enumerate(results, start=1):
        url = result.get("url", "").strip()

        if not url:
            continue

        print(f"\n[{index}/{len(results)}] Processing: {url}")

        lead = process_website(url)

        if lead.get("error"):
            failed += 1
            print(f"Website processing failed: {lead['error']}")
            continue

        processed += 1
        print(f"Company: {lead.get('company_name', 'Unknown')}")
        print(f"Lead ID: {lead.get('id', 'Not returned')}")

        qualification = lead.get("ai_qualification")
        if qualification:
            print(f"Buyer status: {qualification.get('buyer_status')}")
            print(
                "Recommended action: "
                f"{qualification.get('recommended_next_action')}"
            )
        elif lead.get("ai_qualification_error"):
            print(
                "AI qualification failed: "
                f"{lead['ai_qualification_error']}"
            )

    print("\n--- Pipeline summary ---")
    print(f"Candidate websites: {len(results)}")
    print(f"Successfully processed: {processed}")
    print(f"Failed website processing: {failed}")


if __name__ == "__main__":
    run_discovery_pipeline()
