
import re

from app.database import (
    get_all_leads,
    has_been_contacted,
    record_outreach,
)
from app.gmail_drafts import create_draft


MIN_CONFIDENCE = 50

PRODUCTS = "fresh oranges, grapes, and pomegranates"


def valid_email(email):
    """Basic format check; this does not prove the address exists."""
    return bool(
        email
        and re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",
            email.strip(),
        )
    )


def eligible_leads():
    """Return qualified leads only; never send from this function."""
    leads = get_all_leads()
    eligible = []

    for lead in leads:
        email = (lead.get("email") or "").strip()

        if not valid_email(email):
            continue

        if lead.get("buyer_status") != "potential_buyer":
            continue

        if int(lead.get("ai_confidence") or 0) < MIN_CONFIDENCE:
            continue

        if lead.get("recommended_next_action") != "investigate_website":
            continue

        company = (lead.get("company_name") or "").strip().lower()

        if not company or company in {
            "unknown", "home", "wholesale", "redirection page"
        }:
            continue

        if email.lower().endswith("@example.com"):
            continue

        if not has_been_contacted(lead["id"], email):
            eligible.append(lead)

    return eligible


def prepare_email(lead):
    """Prepare a personalized email for a human to review."""
    company = lead.get("company_name") or "your team"
    country = lead.get("country") or ""
    greeting = f"Hello {company} team,"

    location_sentence = (
        f"We understand that your business operates in {country}. "
        if country else ""
    )

    subject = "Fresh Produce Supply from EGAST"

    body = (
        f"{greeting}\n\n"
        f"My name is Roaa, and I'm contacting you on behalf of EGAST, "
        f"an Egyptian grower and exporter of fresh produce.\n\n"
        f"We supply {PRODUCTS}. {location_sentence}"
        f"We would welcome the opportunity to learn about your sourcing "
        f"requirements and discuss whether our products could be a fit "
        f"for your business.\n\n"
        f"If this is relevant to your purchasing team, would you be "
        f"available for a brief conversation?\n\n"
        f"Best regards,\n"
        f"Roaa\n"
        f"EGAST Group"
    )

    return subject, body


def preview_outreach():
    """Display potential recipients and messages without sending."""
    leads = eligible_leads()

    print(f"\nEligible leads: {len(leads)}")
    print("PREVIEW ONLY — no emails will be sent.\n")

    for lead in leads:
        subject, body = prepare_email(lead)

        print("=" * 60)
        print(f"Lead ID: {lead['id']}")
        print(f"Company: {lead['company_name']}")
        print(f"To: {lead['email']}")
        print(f"Subject: {subject}")
        print(f"\n{body}\n")

    if not leads:
        print(
            "No leads meet the current qualification threshold. "
            "Review the AI qualifications before outreach."
        )


def approve_and_send(lead_id):
    """Send one eligible lead's email after explicit terminal approval."""
    leads = eligible_leads()
    lead = next(
        (item for item in leads if item["id"] == lead_id),
        None,
    )

    if lead is None:
        raise ValueError(
            "Lead is not eligible. No email was sent."
        )

    subject, body = prepare_email(lead)

    print("\nReview this message before sending:")
    print(f"To: {lead['email']}")
    print(f"Company: {lead['company_name']}")
    print(f"Subject: {subject}")
    print(f"\n{body}\n")

    confirmation = input(
        "To send this email, type the recipient address exactly: "
    ).strip()

    if confirmation.casefold() != lead["email"].casefold():
        print("Not sent. Recipient confirmation did not match.")
        return False

    send_email(lead["email"], subject, body)
    print("Gmail accepted the message for sending.")
    return True

def create_lead_drafts():
    """Create Gmail drafts for eligible leads; never send emails."""
    leads = eligible_leads()

    if not leads:
        print("No eligible leads found.")
        return

    print(f"\nEligible leads: {len(leads)}")
    print("This will save drafts in Gmail. It will not send emails.")

    for lead in leads:
        subject, body = prepare_email(lead)

        print("\n" + "=" * 60)
        print(f"Company: {lead['company_name']}")
        print(f"Recipient: {lead['email']}")
        print(f"Subject: {subject}")
        print(body)

        confirmation = input(
            "\nType CREATE DRAFT to save this email, or press Enter to skip: "
        ).strip()

        if confirmation != "CREATE DRAFT":
            print("Skipped.")
            continue

        draft_id = create_draft(
            recipient=lead["email"],
            subject=subject,
            body=body,
        )

        print(f"Draft saved successfully. Draft ID: {draft_id}")


if __name__ == "__main__":
    create_lead_drafts()


