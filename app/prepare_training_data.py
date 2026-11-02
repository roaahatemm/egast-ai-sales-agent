import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.local_ai_qualifier import qualify_lead

INPUT = ROOT / "data/reference_contacts/Madrid  business cards 2026.xlsx"
OUTPUT = ROOT / "data/training/madrid_training_candidates.csv"


def clean(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Excel file not found: {INPUT}")

    contacts = pd.read_excel(INPUT, sheet_name="export")
    results = []

    for index, row in contacts.iterrows():
        company = clean(row.get("Company"))
        title = clean(row.get("Contact Person, Title"))
        website = clean(row.get("Web Site"))
        country = clean(row.get("Business Country/Region"))
        email = clean(row.get("E-Mail"))

        lead = {
            "company_name": company,
            "website": website,
            "source_url": website,
            "description": (
                f"Business-card contact. Job title: {title}. "
                f"Email: {email}. Country: {country}. "
                "Determine whether the company is a potential buyer "
                "of fresh oranges, grapes, or pomegranates. "
                "Do not assume a company buys produce based only "
                "on the person's job title."
            ),
            "country": country,
            "industry": "",
            "products": [
                "Fresh oranges",
                "Fresh grapes",
                "Fresh pomegranates",
            ],
        }

        print(f"[{index + 1}/{len(contacts)}] Qualifying: {company}")

        try:
            result = qualify_lead(lead)
            results.append({
                "company": company,
                "contact_name": clean(row.get("Contact Person …")),
                "title": title,
                "email": email,
                "phone": clean(row.get("Contact Person, Telephone 1")),
                "mobile": clean(row.get("Contact Person, Mobile Phone")),
                "country": country,
                "website": website,
                "suggested_buyer_status": result.get("buyer_status", "uncertain"),
                "suggested_buyer_type": result.get("buyer_type", "unknown"),
                "suggested_products": str(result.get("products_of_interest", [])),
                "suggested_confidence": result.get("confidence", 0),
                "suggested_reason": result.get("qualification_reason", ""),
                "evidence": str(result.get("evidence", [])),
                "reviewed_label": "",
                "review_notes": "",
            })
        except Exception as exc:
            print(f"  Error: {exc}")
            results.append({
                "company": company,
                "contact_name": clean(row.get("Contact Person …")),
                "title": title,
                "email": email,
                "phone": clean(row.get("Contact Person, Telephone 1")),
                "mobile": clean(row.get("Contact Person, Mobile Phone")),
                "country": country,
                "website": website,
                "suggested_buyer_status": "uncertain",
                "suggested_buyer_type": "unknown",
                "suggested_products": "",
                "suggested_confidence": 0,
                "suggested_reason": "AI qualification failed; manual review required.",
                "evidence": "",
                "reviewed_label": "",
                "review_notes": str(exc),
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    print(f"\nFinished. Saved {len(results)} rows to:\n{OUTPUT}")
    print("Review the suggestions before using them as training examples.")


if __name__ == "__main__":
    main()
