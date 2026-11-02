
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

# Paths
ROOT = Path(__file__).resolve().parent.parent
EXCEL_FILE = (
    ROOT / "data" / "reference_contacts"
    / "Madrid  business cards 2026.xlsx"
)
DB_FILE = ROOT / "data" / "leads.db"
REPORT_FILE = ROOT / "data" / "madrid_contact_match_report.xlsx"


def clean(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_email(value):
    return clean(value).lower()


def normalize_website(value):
    value = clean(value).lower()
    if not value:
        return ""

    if "://" not in value:
        value = "https://" + value

    try:
        host = (urlparse(value).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except ValueError:
        return ""


def normalize_name(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def read_existing_leads():
    with sqlite3.connect(DB_FILE) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM leads"
            ).fetchall()
        ]


def classify_contact(contact, leads):
    email = normalize_email(contact["email"])
    website = normalize_website(contact["website"])
    company = normalize_name(contact["company"])

    # Exact email match takes priority.
    if email:
        matches = [
            lead for lead in leads
            if normalize_email(lead.get("email")) == email
        ]
        if matches:
            return "EXACT_EMAIL_MATCH", matches

    # Exact website/domain match.
    if website:
        matches = [
            lead for lead in leads
            if normalize_website(lead.get("website")) == website
        ]
        if matches:
            return "WEBSITE_MATCH", matches

    # Exact normalized company name only.
    # Similar-looking names are not automatically merged.
    if company:
        matches = [
            lead for lead in leads
            if normalize_name(lead.get("company_name")) == company
        ]
        if matches:
            return "EXACT_COMPANY_NAME_REVIEW", matches

    return "NO_MATCH", []


def main():
    if not EXCEL_FILE.exists():
        raise FileNotFoundError(
            f"Excel file not found: {EXCEL_FILE}"
        )

    if not DB_FILE.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_FILE}"
        )

    contacts = pd.read_excel(EXCEL_FILE, sheet_name="export")
    leads = read_existing_leads()

    required_columns = [
        "Company",
        "Contact Person …",
        "Contact Person, First Name",
        "Contact Person, Last Name",
        "Contact Person, Title",
        "E-Mail",
        "Contact Person, Telephone 1",
        "Contact Person, Telephone 2",
        "Contact Person, Mobile Phone",
        "Business Country/Region",
        "Web Site",
    ]

    missing = [
        column for column in required_columns
        if column not in contacts.columns
    ]
    if missing:
        raise ValueError(f"Missing Excel columns: {missing}")

    report = []

    for _, row in contacts.iterrows():
        contact = {
            "company": clean(row["Company"]),
            "contact_name": clean(row["Contact Person …"]),
            "first_name": clean(row["Contact Person, First Name"]),
            "last_name": clean(row["Contact Person, Last Name"]),
            "title": clean(row["Contact Person, Title"]),
            "email": clean(row["E-Mail"]),
            "phone_1": clean(row["Contact Person, Telephone 1"]),
            "phone_2": clean(row["Contact Person, Telephone 2"]),
            "mobile": clean(row["Contact Person, Mobile Phone"]),
            "country": clean(row["Business Country/Region"]),
            "website": clean(row["Web Site"]),
        }

        match_type, matches = classify_contact(contact, leads)

        purchasing_terms = (
            "purchasing",
            "procurement",
            "buying",
            "import",
            "sourcing",
        )
        title = contact["title"].casefold()
        purchasing_signal = any(
            term in title for term in purchasing_terms
        )

        report.append({
            **contact,
            "match_status": match_type,
            "matched_lead_ids": ", ".join(
                str(lead["id"]) for lead in matches
            ),
            "matched_company_names": " | ".join(
                clean(lead.get("company_name"))
                for lead in matches
            ),
            "purchasing_title_signal": purchasing_signal,
            "recommended_review": (
                "Review buyer evidence and contact details"
                if purchasing_signal
                else "Review company relevance and contact details"
            ),
        })

    result = pd.DataFrame(report)

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_excel(REPORT_FILE, index=False)

    print("\nMATCH REPORT COMPLETE")
    print(f"Contacts checked: {len(result)}")
    print(f"Existing leads checked: {len(leads)}")
    print("\nMatch counts:")
    print(result["match_status"].value_counts().to_string())
    print(f"\nReport saved to:\n{REPORT_FILE}")
    print("\nNo database records were modified.")


if __name__ == "__main__":
    main()
