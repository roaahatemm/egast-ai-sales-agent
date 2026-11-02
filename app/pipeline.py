
from time import perf_counter

from requests.exceptions import RequestException

from app.scraper import scrape_page_with_html
from app.extractor import extract_lead
from app.scoring import score_lead
from app.database import (
    save_lead,
    save_ai_qualification,
    save_ml_assessment,
)
from app.local_ai_qualifier import qualify_lead
from app.ml_qualifier import predict_buyer


def process_website(url: str) -> dict:
    """Scrape, extract, score, save, and qualify a potential lead."""

    total_start = perf_counter()

    try:
        website_start = perf_counter()

        html, links = scrape_page_with_html(url)
        lead = extract_lead(html, url)

        # Ensure the source URL is saved for deduplication.
        lead["website"] = url

        lead["score"] = score_lead(lead)
        lead["discovered_links"] = [
            item["url"] for item in links
        ]

        lead["website_processing_seconds"] = round(
            perf_counter() - website_start, 2
        )

        # Save the lead first so AI failures won't lose it.
        lead["id"] = save_lead(lead)

        # ML is advisory only; Ollama remains the primary qualifier.
        try:
            ml_assessment = predict_buyer(lead)
        except Exception as ml_error:
            ml_assessment = {
                "available": False,
                "error": (
                    f"{type(ml_error).__name__}: {ml_error}"
                ),
            }

        lead["ml_assessment"] = ml_assessment

        # Persist the initial ML result independently.
        try:
            save_ml_assessment(
                lead["id"],
                ml_assessment,
            )
        except Exception as db_error:
            lead["ml_assessment_save_error"] = (
                f"{type(db_error).__name__}: {db_error}"
            )

        ai_start = perf_counter()

        try:
            # Qualify the lead using Ollama.
            qualification = qualify_lead(lead)

            # Compare classifications only when ML is available.
            if ml_assessment.get("available"):
                ollama_status = qualification.get(
                    "buyer_status"
                )
                ml_status = ml_assessment.get("prediction")

                if ollama_status and ml_status:
                    agrees = ollama_status == ml_status
                else:
                    agrees = None

                ml_assessment["agrees_with_ollama"] = agrees

                # Do not treat missing classifications as agreement.
                ml_assessment["review_required"] = (
                    agrees is False
                )

                # Persist the updated assessment, including review flag.
                try:
                    save_ml_assessment(
                        lead["id"],
                        ml_assessment,
                    )
                    lead.pop(
                        "ml_assessment_save_error",
                        None,
                    )
                except Exception as db_error:
                    lead["ml_assessment_save_error"] = (
                        f"{type(db_error).__name__}: {db_error}"
                    )

            save_ai_qualification(
                lead["id"],
                qualification=qualification,
            )

            lead["ai_qualification"] = qualification

        except Exception as ai_error:
            error_message = (
                f"{type(ai_error).__name__}: {ai_error}"
            )

            lead["ai_qualification_error"] = error_message

            try:
                save_ai_qualification(
                    lead["id"],
                    error=error_message,
                )
            except Exception as db_error:
                lead["ai_qualification_save_error"] = (
                    f"{type(db_error).__name__}: {db_error}"
                )

        finally:
            lead["ai_qualification_seconds"] = round(
                perf_counter() - ai_start, 2
            )

        print(
            f"[TIMING] website="
            f"{lead['website_processing_seconds']:.2f}s | "
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
        print(
            f"[TIMING] {url} | total={total_seconds:.2f}s"
        )


def process_websites(urls: list[str]) -> list[dict]:
    """Process multiple websites sequentially."""

    return [process_website(url) for url in urls]
