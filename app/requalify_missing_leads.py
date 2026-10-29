import sqlite3
from app.database import DATABASE_PATH, save_ai_qualification
from app.scraper import scrape_page_with_html
from app.extractor import extract_lead
from app.local_ai_qualifier import qualify_lead


def main():
    with sqlite3.connect(DATABASE_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT *
            FROM leads
            WHERE buyer_status IS NULL OR TRIM(buyer_status) = ''
            ORDER BY id
        """).fetchall()

    print(f"Found {len(rows)} leads without AI qualification.")
    succeeded = 0
    failed = 0

    for row in rows:
        lead = dict(row)
        lead_id = lead["id"]
        website = lead.get("website") or ""
        print(f"\n[{lead_id}] {lead.get('company_name')} — {website}")

        # Try to recover missing details from the existing website.
        if website:
            try:
                html, links = scrape_page_with_html(website)
                scraped = extract_lead(html, website)

                # Prefer recovered non-empty details; retain saved values
                # whenever scraping doesn't provide a usable replacement.
                for key, value in scraped.items():
                    if value not in (None, "", [], {}):
                        lead[key] = value

                lead["website"] = website
                lead["source_url"] = lead.get("source_url") or website
                lead["discovered_links"] = [
                    item["url"] for item in links
                    if isinstance(item, dict) and item.get("url")
                ]
                print("Website scrape: successful")
            except Exception as exc:
                print(f"Website scrape: failed ({type(exc).__name__}: {exc})")
                lead["source_url"] = lead.get("source_url") or website

        try:
            qualification = qualify_lead(lead)
            save_ai_qualification(
                lead_id,
                qualification=qualification,
            )
            succeeded += 1
            print(
                f"AI result: {qualification['buyer_status']} | "
                f"confidence={qualification['confidence']}"
            )
        except Exception as exc:
            failed += 1
            message = f"{type(exc).__name__}: {exc}"
            save_ai_qualification(lead_id, error=message)
            print(f"AI qualification failed: {message}")

    print("\n=== REQUALIFICATION SUMMARY ===")
    print(f"Successful: {succeeded}")
    print(f"Failed: {failed}")
    print("Only AI qualification fields were updated.")


if __name__ == "__main__":
    main()
