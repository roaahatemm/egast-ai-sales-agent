
import json
import os
import requests

# Local Ollama configuration.
# For Ollama Cloud, configure these environment variables:
# OLLAMA_URL=https://ollama.com/api/chat
# OLLAMA_MODEL=<your supported model>
# OLLAMA_API_KEY=<your API key>

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()

OLLAMA_HEADERS = (
    {"Authorization": f"Bearer {OLLAMA_API_KEY}"}
    if OLLAMA_API_KEY
    else {}
)

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
            ],
        },
        "products_of_interest": {
            "type": "array",
            "items": {"type": "string"},
        },
        "target_country": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "qualification_reason": {"type": "string"},
        "confidence": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        },
        "recommended_next_action": {
            "type": "string",
            "enum": [
                "review_lead",
                "investigate_website",
                "consider_for_outreach",
                "reject_lead",
            ],
        },
    },
    "required": [
        "is_company",
        "buyer_status",
        "buyer_type",
        "products_of_interest",
        "target_country",
        "evidence",
        "qualification_reason",
        "confidence",
        "recommended_next_action",
    ],
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
    Qualify a lead using local Ollama.

    The model must use supplied evidence rather than inventing
    company details. A human must review leads before outreach.
    """
    if not isinstance(lead, dict):
        raise TypeError("lead must be a dictionary.")

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

1. Use only the supplied lead data. You have not independently
   visited or verified the website.
2. A company name, URL, country, or industry label alone does not
   prove that a company exists or imports produce.
3. Never invent company activities, locations, products, import
   history, customers, or business relationships.
4. Supplied products are not proof that the company buys them.
5. Claim importing is established only if the supplied description
   explicitly supports that claim.
6. If evidence is insufficient or contradictory, choose uncertain.
7. Set is_company to false only if the supplied data explicitly
   establishes that the lead is not a company or is fictional.
8. Use the supplied country for target_country when present.
   Otherwise return an empty string.
9. List only products supported by the supplied description or data.
10. Evidence must describe information actually present in the input.
11. Confidence must reflect the strength of the supplied evidence.
12. If buyer_status is uncertain, recommended_next_action must be
    review_lead or investigate_website.
13. Never recommend outreach based solely on a name, URL, or
    generic industry label.

CLASSIFICATION GUIDANCE:

- potential_buyer: Evidence supports that the company is a relevant
  buyer, importer, wholesaler, or distributor of fresh produce.
- not_buyer: Evidence clearly indicates that the lead is not a
  relevant potential buyer.
- uncertain: Evidence is insufficient to decide.

Return only JSON matching the required schema.
Keep qualification_reason concise.
"""

    request_payload = {
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
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": SCHEMA,
        "options": {
            "temperature": 0,
            "num_predict": 400,
        },
    }

    # Retry once if the model returns invalid JSON.
    qualification = None
    last_json_error = None

    for attempt in range(2):
        if attempt == 1:
            request_payload["messages"].append({
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Return only one valid JSON object matching the "
                    "required schema. Do not include Markdown fences."
                ),
            })

        try:
            response = requests.post(
                OLLAMA_URL,
                headers=OLLAMA_HEADERS,
                json=request_payload,
                timeout=300,
            )
            response.raise_for_status()
            response_data = response.json()

        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not connect to Ollama at {OLLAMA_URL}: {exc}"
            ) from exc

        except ValueError as exc:
            raise RuntimeError(
                "Ollama returned a response that was not valid JSON."
            ) from exc

        if not isinstance(response_data, dict):
            raise RuntimeError("Ollama response must be a JSON object.")

        message = response_data.get("message", {})

        if not isinstance(message, dict):
            raise RuntimeError(
                "Ollama response is missing a valid 'message' object."
            )

        content = message.get("content")

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                "Ollama returned empty or invalid message content."
            )

        try:
            qualification = json.loads(content)
            break
        except json.JSONDecodeError as exc:
            last_json_error = exc

    if qualification is None:
        raise ValueError(
            "Ollama returned invalid JSON after one retry."
        ) from last_json_error

    if not isinstance(qualification, dict):
        raise ValueError("Ollama qualification must be a JSON object.")

    # Verify all required fields are present.
    missing_fields = [
        field
        for field in SCHEMA["required"]
        if field not in qualification
    ]

    if missing_fields:
        raise ValueError(
            f"AI response is missing required fields: {missing_fields}"
        )

    # Validate basic field types.
    if not isinstance(qualification["is_company"], bool):
        raise ValueError("is_company must be a boolean.")

    string_fields = [
        "buyer_status",
        "buyer_type",
        "target_country",
        "qualification_reason",
        "recommended_next_action",
    ]

    for field in string_fields:
        if not isinstance(qualification[field], str):
            raise ValueError(f"{field} must be a string.")

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

    confidence = qualification["confidence"]

    if isinstance(confidence, bool) or not isinstance(confidence, int):
        raise ValueError("confidence must be an integer.")

    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be between 0 and 100.")

    # Application-level safeguards.
    description = website_data["description"].lower()

    # Avoid treating an exporter that explicitly does not buy from
    # suppliers as a confirmed buyer.
    explicit_non_purchaser_phrases = (
        "do not purchase",
        "does not purchase",
        "don't purchase",
        "doesn't purchase",
        "do not buy from other suppliers",
        "does not buy from other suppliers",
        "we do not buy",
        "we don't buy",
        "we do not purchase",
        "we don't purchase",
        "not purchase produce from other suppliers",
    )

    says_it_does_not_purchase = any(
        phrase in description
        for phrase in explicit_non_purchaser_phrases
    )

    exporter_terms = (
        "exporter",
        "export our",
        "export its",
        "exports",
    )

    mentions_exporting = (
        any(term in description for term in exporter_terms)
        or "exporter" in website_data["industry"].lower()
    )

    if says_it_does_not_purchase and mentions_exporting:
        qualification["buyer_status"] = "uncertain"
        qualification["buyer_type"] = "unknown"
        qualification["products_of_interest"] = []
        qualification["confidence"] = min(
            qualification["confidence"], 40
        )
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    # If the model is uncertain, don't treat the lead as a confirmed buyer.
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

    # A lead marked as not a company cannot be a confirmed buyer.
    if not qualification["is_company"]:
        qualification["buyer_status"] = "uncertain"
        qualification["buyer_type"] = "unknown"
        qualification["products_of_interest"] = []
        qualification["confidence"] = min(
            qualification["confidence"], 40
        )
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    # Clearly irrelevant leads should not be sent for outreach.
    if qualification["buyer_status"] == "not_buyer":
        qualification["recommended_next_action"] = "reject_lead"
        qualification["products_of_interest"] = []

    # Never authorize outreach automatically.
    if qualification["recommended_next_action"] == "consider_for_outreach":
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    # Non-buyers and uncertain leads should not retain product interests.
    if qualification["buyer_status"] != "potential_buyer":
        qualification["products_of_interest"] = []

    return qualification
