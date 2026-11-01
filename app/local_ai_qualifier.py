
import json
import os
import time

import requests


# Gemini configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
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


def _gemini_schema(schema):
    """Convert the JSON schema to Gemini-compatible responseSchema."""
    if isinstance(schema, dict):
        result = {}

        for key, value in schema.items():
            if key in {"minimum", "maximum"}:
                continue

            if key == "type" and isinstance(value, str):
                result[key] = value.upper()
            else:
                result[key] = _gemini_schema(value)

        return result

    if isinstance(schema, list):
        return [_gemini_schema(item) for item in schema]

    return schema


def qualify_lead(lead: dict) -> dict:
    """
    Qualify a lead using Gemini and supplied evidence only.
    Application-level safeguards remain authoritative.
    AI qualification never independently authorizes outreach.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Add it to your environment or Streamlit Secrets."
        )

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
8. Use the supplied country for target_country only when present.
   If no country is supplied, return an empty string.
9. products_of_interest must contain only products explicitly
   supported by the supplied description or product data.
10. Evidence must describe information actually present in the
    input. Do not present assumptions as verified facts.
11. Confidence must reflect the strength of the supplied evidence.
    A URL alone or vague description should produce low confidence.
12. If buyer_status is uncertain, recommended_next_action must
    be "review_lead" or "investigate_website".
13. Do not recommend outreach based solely on a company name,
    URL, or generic industry label.

CLASSIFICATION GUIDANCE:

- potential_buyer:
  Evidence supports that the company is a relevant buyer,
  importer, wholesaler, or distributor of fresh produce.

- not_buyer:
  Evidence clearly indicates that the lead is not a relevant
  potential buyer.

- uncertain:
  Evidence is insufficient to make either conclusion.

Return only JSON matching the required schema.
Keep qualification_reason concise.
"""

    retry_instruction = (
        "Your previous response was not valid JSON. Return only one valid "
        "JSON object matching the required schema. Do not include Markdown "
        "fences or explanatory text."
    )

    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are a conservative business lead classifier. "
                        "Never fabricate facts. Follow the schema exactly. "
                        "When evidence is insufficient, classify as uncertain."
                    )
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 600,
            "responseMimeType": "application/json",
            "responseSchema": _gemini_schema(SCHEMA),
        },
    }

    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    qualification = None
    last_json_error = None
    json_retry_used = False
    transient_retry_used = False

    while qualification is None:
        try:
            response = requests.post(
                GEMINI_API_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )

            if (
                response.status_code in (429, 500, 502, 503, 504)
                and not transient_retry_used
            ):
                transient_retry_used = True
                time.sleep(1)
                continue

            response.raise_for_status()
            response_data = response.json()

            # Gemini response format and compatibility with existing tests.
            if "candidates" in response_data:
                try:
                    content = response_data["candidates"][0]["content"][
                        "parts"
                    ][0]["text"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise ValueError(
                        "Gemini returned an unexpected response structure."
                    ) from exc

            elif (
                isinstance(response_data.get("message"), dict)
                and isinstance(
                    response_data["message"].get("content"), str
                )
            ):
                content = response_data["message"]["content"]

            elif "error" in response_data:
                raise ValueError(
                    f"Gemini API error: {response_data['error']}"
                )

            else:
                raise ValueError(
                    "Gemini returned an unexpected response structure."
                )

        except (requests.Timeout, requests.ConnectionError):
            if not transient_retry_used:
                transient_retry_used = True
                time.sleep(1)
                continue
            raise

        try:
            qualification = json.loads(content)

        except json.JSONDecodeError as exc:
            last_json_error = exc

            if json_retry_used:
                break

            json_retry_used = True

            payload["contents"].append(
                {
                    "role": "model",
                    "parts": [{"text": content}],
                }
            )
            payload["contents"].append(
                {
                    "role": "user",
                    "parts": [{"text": retry_instruction}],
                }
            )

    if qualification is None:
        raise ValueError(
            "Gemini returned invalid JSON after one retry."
        ) from last_json_error

    if not isinstance(qualification, dict):
        raise ValueError("AI response must be a JSON object.")

    # Verify required fields.
    missing_fields = [
        field for field in SCHEMA["required"] if field not in qualification
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
        isinstance(item, str) for item in qualification["evidence"]
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
    if qualification["recommended_next_action"] == "consider_for_outreach":
        qualification["recommended_next_action"] = (
            "investigate_website"
            if website_data["website"]
            else "review_lead"
        )

    # Unqualified leads must not retain product interests.
    if qualification["buyer_status"] != "potential_buyer":
        qualification["products_of_interest"] = []

    return qualification
