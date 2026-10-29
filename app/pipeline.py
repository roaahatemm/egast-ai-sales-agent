
from time import perf_counter

from requests.exceptions import RequestException

from app.scraper import scrape_page_with_html
from app.extractor import extract_lead
from app.scoring import score_lead
from app.database import save_lead, save_ai_qualification
from app.local_ai_qualifier import qualify_lead


def process_website(url: str) -> dict:
    """Scrape, extract, score, save, and qualify a potential lead."""

    total_start = perf_counter()

    try:
        website_start = perf_counter()

        html, links = scrape_page_with_html(url)
        lead = extract_lead(html, url)
        lead["score"] = score_lead(lead)
        lead["discovered_links"] = [item["url"] for item in links]

        lead["website_processing_seconds"] = round(
            perf_counter() - website_start, 2
        )

        # Save the lead first so AI failure won't lose it.
        lead["id"] = save_lead(lead)

        # Qualify the saved lead using local Ollama.
        ai_start = perf_counter()

        try:
            qualification = qualify_lead(lead)

            save_ai_qualification(
                lead["id"],
                qualification=qualification,
            )
            lead["ai_qualification"] = qualification

        except Exception as ai_error:
            error_message = f"{type(ai_error).__name__}: {ai_error}"

            save_ai_qualification(
                lead["id"],
                error=error_message,
            )
            lead["ai_qualification_error"] = error_message

        finally:
            lead["ai_qualification_seconds"] = round(
                perf_counter() - ai_start, 2
            )

        print(
            f"[TIMING] website={lead['website_processing_seconds']:.2f}s | "
            f"AI={lead['ai_qualification_seconds']:.2f}s"
        )

        return lead

    except (ValueError, RequestException) as exc:
        return {
            "source_url": url,
            "error": str(exc),
        }

    finally:
        total_seconds = perf_counter() - total_start
        print(f"[TIMING] {url} | total={total_seconds:.2f}s")


def process_websites(urls: list[str]) -> list[dict]:
    """Process multiple websites sequentially."""

    return [process_website(url) for url in urls]

