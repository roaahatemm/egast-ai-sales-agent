import json
import os
import requests

# Local Ollama remains the default for development.
# For Streamlit Cloud, set these values in App Settings -> Secrets:
# OLLAMA_URL = "https://ollama.com/api/chat"
# OLLAMA_MODEL = "<a model name supported by your Ollama Cloud account>"
# OLLAMA_API_KEY = "<your Ollama API key>"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
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
    Qualify an existing lead using local Ollama.

    The model must use supplied evidence rather than inventing
    company details. Final decisions still require human review.
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

Your task is to assess whether the supplied lead could be a buyer
of fresh produce.

LEAD DATA:
{json.dumps(website_data, ensure_ascii=False, indent=2)}

STRICT EVIDENCE RULES:

1. Use only the supplied lead data. You have not independently
   visited or verified the website.
2. A company name, website URL, country field, or industry label
   is not proof that a company exists or imports produce.
3. Do not invent company activities, locations, products,
   import history, customers, or business relationships.
4. Treat supplied products as associated lead data, not proof
   that the company buys those products.
5. Only describe importing as established evidence if the supplied
   description explicitly states that the company imports products.
6. If evidence is sparse, contradictory, fictional, or insufficient,
   choose buyer_status = "uncertain".
7. Set is_company to false only when the supplied data explicitly
   establishes that the lead is fictional or is not a company.
   Otherwise, use the available evidence cautiously.
8. Do not confuse the company's country with EGAST's origin.
   Use the supplied country for target_country only when present.
   If no country is supplied, return an empty string.
9. products_of_interest must contain only products explicitly
   supported by the supplied description or product data.
10. Evidence must describe information actually present in the
    input. Do not present assumptions as verified facts.
11. Confidence must reflect the strength of the supplied evidence.
    A URL alone or a vague description should produce low confidence.
12. If buyer_status is uncertain, recommended_next_action must
    be "review_lead" or "investigate_website".
13. Do not recommend outreach based solely on a company name,
    URL, or generic industry label.

CLASSIFICATION GUIDANCE:

- potential_buyer:
  The supplied evidence supports that the company is a relevant
  buyer, importer, wholesaler, or distributor of fresh produce.

- not_buyer:
  The supplied evidence clearly indicates that the lead is not
  a relevant potential buyer.

- uncertain:
  The supplied evidence is insufficient to make either conclusion.

Return only JSON matching the required schema.
Keep the qualification_reason concise.
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
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "format": SCHEMA,
        "options": {
            "temperature": 0,
            "num_predict": 400,
        },
    }

    # Retry once if Ollama returns content that is not valid JSON.
    qualification = None
    last_json_error = None

    for attempt in range(2):
        if attempt == 1:
            request_payload["messages"].append({
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Return only one valid JSON object matching the required schema. "
                    "Do not include Markdown fences or explanatory text."
                ),
            })

        response = requests.post(
            OLLAMA_URL,
            headers=OLLAMA_HEADERS,
            json=request_payload,
            timeout=300,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]

        try:
            qualification = json.loads(content)
            break
        except json.JSONDecodeError as exc:
            last_json_error = exc

    if qualification is None:
        raise ValueError(
            "Ollama returned invalid JSON after one retry."
        ) from last_json_error

    # Verify required fields.
    missing_fields = [
        field for field in SCHEMA["required"]
        if field not in qualification
    ]

    if missing_fields:
        raise ValueError(
            f"AI response is missing required fields: {missing_fields}"
        )

    # Validate field types and allowed values.
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

    # Conservative application-level safeguards.
    description = website_data["description"].lower()

    # An exporter that explicitly says it does not purchase from suppliers
    # must not be automatically classified as a buyer.
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
        phrase in description for phrase in explicit_non_purchaser_phrases
    )
    exporter_terms = ("exporter", "export our", "export its", "exports")
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

    # Look for explicit importing language, while avoiding common
    # phrases that deny or negate importing.
    negative_import_phrases = (
        "does not import",
        "do not import",
        "doesn't import",
        "not an importer",
        "no imports",
        "never imports",
    )
    has_negative_import_statement = any(
        phrase in description for phrase in negative_import_phrases
    )
    explicit_import_evidence = (
        not has_negative_import_statement
        and any(
            term in description
            for term in ("import", "importer", "imports", "importing")
        )
    )

    # Uncertain leads must not be treated as confirmed buyers.
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

    # A clear non-buyer should not be sent for outreach.
    if qualification["buyer_status"] == "not_buyer":
        qualification["recommended_next_action"] = "reject_lead"
        qualification["products_of_interest"] = []

    # The qualifier must never authorize outreach by itself.
    # A sales employee should review the lead and decide whether to contact it.
    # Keep the action conservative even when the AI suggests outreach.
    if qualification["recommended_next_action"] == "consider_for_outreach":
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    # Unqualified leads must not retain product interests or outreach.
    if qualification["buyer_status"] != "potential_buyer":
        qualification["products_of_interest"] = []
        if qualification["recommended_next_action"] == "consider_for_outreach":
            qualification["recommended_next_action"] = "review_lead"

    return qualification