

import json
import time
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b"


SCHEMA = {
    "type": "object",
    "properties": {
        "is_company": {"type": "boolean"},
        "buyer_status": {
            "type": "string",
            "enum": ["potential_buyer", "not_buyer", "uncertain"],
        },
        "buyer_type": {
            "type": "string",
            "enum": [
                "importer", "wholesaler", "distributor", "retailer",
                "exporter", "producer", "marketplace", "market_report",
                "other", "unknown",
            ],
        },
        "products_of_interest": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 40},
        },
        "target_country": {"type": "string", "maxLength": 100},
        "evidence": {
            "type": "array",
            "maxItems": 2,
            "items": {"type": "string", "maxLength": 100},
        },
        "qualification_reason": {"type": "string", "maxLength": 140},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "recommended_next_action": {
            "type": "string",
            "enum": [
                "review_lead", "investigate_website",
                "consider_for_outreach", "reject_lead",
            ],
        },
    },
    "required": [
        "is_company", "buyer_status", "buyer_type", "products_of_interest",
        "target_country", "evidence", "qualification_reason", "confidence",
        "recommended_next_action",
    ],
    "additionalProperties": False,
}

def clean_text(value, limit=1500):
    """Convert a supplied value into safe, readable text."""
    if value is None:
        return ""

    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)

    return str(value).strip()[:limit]


def qualify_lead(lead: dict) -> dict:
    """
    Qualify a potential lead using local Ollama.

    Uses supplied evidence only. Qualification is not independent
    verification of a company or proof of active purchasing demand.
    """

    website_data = {
        "company_name": clean_text(lead.get("company_name"), 200),
        "website": clean_text(lead.get("website"), 500),
        "source_url": clean_text(lead.get("source_url"), 500),
        "description": clean_text(lead.get("description"), 3000),
        "country": clean_text(lead.get("country"), 200),
        "industry": clean_text(lead.get("industry"), 300),
        "products": clean_text(lead.get("products"), 1000),
    }

    prompt = f"""
You are a cautious B2B lead qualification assistant for EGAST,
an Egyptian exporter of fresh oranges, grapes, and pomegranates.

Assess whether the supplied lead could be a buyer of fresh produce.

LEAD DATA:
{json.dumps(website_data, ensure_ascii=False, indent=2)}

STRICT EVIDENCE RULES:

1. Use only the supplied data. You have not independently verified
   this company or visited its website.
2. A name, URL, industry label, or product mention alone does not
   prove that a company purchases fresh produce.
3. Never invent company activities, locations, products, import
   history, customers, or business relationships.
4. Treat supplied products as clues, not proof of purchasing activity.
5. Importing, wholesaling, or distributing is relevant only when
   supported by the supplied description.
6. If evidence is insufficient, choose "uncertain".
7. Do not confuse uncertainty about buyer suitability with whether
   a business exists.
8. Use the supplied country only when one is provided.
9. Include only products supported by the supplied information.
10. Evidence must describe information actually present in the input.
11. Confidence must reflect the strength of the evidence. A URL alone
    or a vague description should produce low confidence.
12. If buyer_status is "uncertain", recommend "review_lead" or
    "investigate_website".
13. Do not recommend outreach based solely on a name or URL.
14. A company exporting its own produce is not automatically a buyer
    of produce from external suppliers.
15. If the description explicitly says the company does not purchase
    produce or does not buy from other suppliers, do not classify it
    as a potential buyer based on that description alone.

CLASSIFICATION:

- potential_buyer: Evidence supports a relevant buyer category,
  such as a fresh-produce importer, wholesaler, or distributor.
- not_buyer: Evidence clearly indicates an unrelated business.
- uncertain: Evidence is insufficient to establish buyer suitability.

OUTPUT QUALITY RULES:

- Keep qualification_reason to one sentence, maximum 20 words.
- Include at most 2 evidence items, each no longer than 12 words.
- Return only the required fields.
- Use short, direct phrases.
- Never repeat facts or explain your reasoning step by step.
- Use only supplied facts; do not invent information.
- Use an empty array when no products are supported.
- Use an empty string when the target country is unknown.
- Return one complete JSON object matching the schema.
"""

    request_started = time.perf_counter()
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a conservative business lead classifier. "
                        "Never fabricate facts. Follow the schema exactly. "
                        "When evidence is insufficient, classify as uncertain."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "stream": False,
            "format": SCHEMA,
            "options": {
                "temperature": 0,
                "num_predict": 350,
            },
        },
        timeout=300,
    )

    
    print(f"[AI TIMING] First Ollama request: {time.perf_counter() - request_started:.2f}s")
    response.raise_for_status()

    response_data = response.json()
    content = response_data["message"]["content"]
    print(f"[AI TIMING] First response length: {len(content)} characters")
    print(f"[AI TIMING] Stop reason: {response_data.get('done_reason')}")
    print(f"[AI TIMING] Generated tokens: {response_data.get('eval_count')}")

    try:
        qualification = json.loads(content)

    except json.JSONDecodeError as exc:
        print(f"[AI TIMING] JSON parsing error: {exc}")
        print(f"[AI TIMING] First response preview: {content[:500]!r}")
        print("[AI TIMING] Invalid JSON; retrying qualification.")
        retry_started = time.perf_counter()
        # Ask Ollama to retry once with a shorter, valid JSON response.
        retry_response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Return one complete, valid JSON object only. "
                            "Follow the supplied schema exactly. "
                            "Do not include markdown or commentary."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Retry the qualification from the original lead data below. "
                            "Return one complete JSON object matching the schema. "
                            "Keep qualification_reason to one short sentence and evidence "
                            "to at most two short items. Do not include commentary.\n\n"
                            f"Original qualification prompt:\n{prompt}"
                        ),
                    },
                ],
                "stream": False,
                "format": SCHEMA,
                "options": {
                    "temperature": 0,
                    "num_predict": 500,
                },
            },
            timeout=300,
        )

        print(f"[AI TIMING] Retry request: {time.perf_counter() - retry_started:.2f}s")
        retry_response.raise_for_status()
        retry_content = retry_response.json()["message"]["content"]
        print(f"[AI TIMING] Retry response length: {len(retry_content)} characters")

        try:
            qualification = json.loads(retry_content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Ollama returned invalid JSON twice; qualification was not saved."
            ) from exc


    # Verify required fields.
    missing_fields = [
        field
        for field in SCHEMA["required"]
        if field not in qualification
    ]

    if missing_fields:
        raise ValueError(
            f"AI response is missing required fields: {missing_fields}"
        )

    # Validate field types.
    if not isinstance(qualification["is_company"], bool):
        raise ValueError("is_company must be a boolean.")

    allowed_statuses = {
        "potential_buyer",
        "not_buyer",
        "uncertain",
    }

    if qualification["buyer_status"] not in allowed_statuses:
        raise ValueError("Invalid buyer_status.")

    allowed_buyer_types = {
        "importer",
        "wholesaler",
        "distributor",
        "retailer",
        "exporter",
        "producer",
        "marketplace",
        "market_report",
        "other",
        "unknown",
    }

    if qualification["buyer_type"] not in allowed_buyer_types:
        raise ValueError("Invalid buyer_type.")

    allowed_actions = {
        "review_lead",
        "investigate_website",
        "consider_for_outreach",
        "reject_lead",
    }

    if qualification["recommended_next_action"] not in allowed_actions:
        raise ValueError("Invalid recommended_next_action.")

    if not isinstance(qualification["products_of_interest"], list):
        raise ValueError("products_of_interest must be a list.")

    if not all(
        isinstance(item, str)
        for item in qualification["products_of_interest"]
    ):
        raise ValueError("Product names must be strings.")

    if not isinstance(qualification["evidence"], list):
        raise ValueError("evidence must be a list.")

    if not all(
        isinstance(item, str)
        for item in qualification["evidence"]
    ):
        raise ValueError("Evidence items must be strings.")

    for field in ["target_country", "qualification_reason"]:
        if not isinstance(qualification[field], str):
            raise ValueError(f"{field} must be a string.")

    confidence = qualification["confidence"]

    if isinstance(confidence, bool) or not isinstance(confidence, int):
        raise ValueError("confidence must be an integer.")

    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be between 0 and 100.")

    # Deterministic safeguards based on the supplied description.
    description = website_data["description"].lower()

    negative_business_phrases = (
        "does not import",
        "do not import",
        "doesn't import",
        "not an importer",
        "no imports",
        "never imports",
        "does not distribute",
        "not a wholesaler",
        "do not purchase produce",
        "does not purchase produce",
        "don't purchase produce",
        "doesn't purchase produce",
        "do not buy produce",
        "does not buy produce",
        "don't buy produce",
        "doesn't buy produce",
        "do not buy from other suppliers",
        "does not buy from other suppliers",
        "do not purchase from other suppliers",
        "does not purchase from other suppliers",
        "do not purchase produce from other suppliers",
        "does not purchase produce from other suppliers",
        "only export our own produce",
        "only exports its own produce",
        "only export our own fruit",
        "only exports its own fruit",
    )

    has_negative_business_statement = any(
        phrase in description for phrase in negative_business_phrases
    )

    # Explicit negative purchasing evidence takes priority over the
    # model's prediction and over positive keyword matches.
    if has_negative_business_statement:
        qualification["buyer_status"] = "uncertain"
        qualification["buyer_type"] = "unknown"
        qualification["confidence"] = min(
            qualification["confidence"], 40
        )
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )
        qualification["qualification_reason"] = (
            "The supplied description contains an explicit statement "
            "about not purchasing or importing produce. Buyer suitability "
            "requires human review."
        )

    else:
        activity_terms = (
            "importer",
            "importers",
            "import",
            "imports",
            "importing",
            "wholesaler",
            "wholesalers",
            "wholesale",
            "distributor",
            "distributors",
            "distribution",
        )

        produce_terms = (
            "fresh produce",
            "fruit",
            "fruits",
            "vegetable",
            "vegetables",
            "citrus",
            "orange",
            "oranges",
            "grape",
            "grapes",
            "pomegranate",
            "pomegranates",
        )

        description_has_activity = any(
            term in description for term in activity_terms
        )
        description_has_produce = any(
            term in description for term in produce_terms
        )

        # A commercial description can support company identity,
        # but a name or website alone cannot establish buyer intent.
        if (
            website_data["website"]
            and description.strip()
            and (
                description_has_activity
                or any(
                    term in description
                    for term in (
                        "company",
                        "supplier",
                        "manufacturer",
                        "retailer",
                        "producer",
                        "exporter",
                        "export",
                        "farm",
                    )
                )
            )
        ):
            qualification["is_company"] = True

        # Exporting own produce is not evidence that the company
        # purchases produce from external suppliers.
        export_only_terms = (
            "export our own",
            "exports its own",
            "export their own",
            "grow and export our own",
            "grows and exports its own",
        )

        explicitly_export_only = any(
            term in description for term in export_only_terms
        )

        explicit_buyer_activity = (
            not explicitly_export_only
            and description_has_activity
            and description_has_produce
        )

        if qualification["is_company"] and explicit_buyer_activity:
            qualification["buyer_status"] = "potential_buyer"

            if any(
                term in description
                for term in ("importer", "importers", "import", "imports", "importing")
            ):
                qualification["buyer_type"] = "importer"
            elif any(
                term in description
                for term in ("wholesaler", "wholesalers", "wholesale")
            ):
                qualification["buyer_type"] = "wholesaler"
            else:
                qualification["buyer_type"] = "distributor"

            qualification["confidence"] = max(
                qualification["confidence"], 50
            )
            qualification["recommended_next_action"] = (
                "investigate_website"
            )
            qualification["qualification_reason"] = (
                "The supplied description identifies a potentially "
                "relevant fresh-produce business. Review the website "
                "to confirm current products and purchasing fit."
            )

    # A clear unrelated business should not be sent for outreach.
    if qualification["buyer_status"] == "not_buyer":
        qualification["recommended_next_action"] = "reject_lead"
        qualification["products_of_interest"] = []

    # Never automatically approve outreach.
    if qualification["recommended_next_action"] == "consider_for_outreach":
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    # Uncertain leads remain unqualified and require review.
    if qualification["buyer_status"] == "uncertain":
        qualification["confidence"] = min(
            qualification["confidence"], 40
        )
        qualification["buyer_type"] = "unknown"
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    if qualification["buyer_status"] != "potential_buyer":
        qualification["products_of_interest"] = []

    return qualification
