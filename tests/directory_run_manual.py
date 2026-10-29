
from app.directory_crawler import crawl_directory

url = input("Enter a public directory URL: ").strip()

try:
    candidates = crawl_directory(
        start_url=url,
        max_pages=3,
        max_results=20,
    )

    print(f"\nCandidates found: {len(candidates)}")

    for number, candidate in enumerate(candidates, start=1):
        print(f"\n{number}. {candidate.get('title') or 'Untitled'}")
        print(f"   URL: {candidate['url']}")
        print(f"   Domain: {candidate['domain']}")
        print(
            "   LinkedIn company page: "
            f"{candidate.get('is_linkedin_company_page', False)}"
        )
        print(f"   Status: {candidate['status']}")

except (ValueError, OSError) as exc:
    print(f"Could not run the test: {exc}")
