
import json
from unittest.mock import Mock, patch

import pytest

from app.local_ai_qualifier import SCHEMA, qualify_lead


def make_qualification(**overrides):
    """Build a valid example response matching the AI schema."""
    result = {
        "is_company": True,
        "buyer_status": "potential_buyer",
        "buyer_type": "importer",
        "products_of_interest": ["oranges", "grapes"],
        "target_country": "Netherlands",
        "evidence": [
            "The description says the company imports fresh oranges."
        ],
        "qualification_reason": (
            "The supplied description supports potential buyer status."
        ),
        "confidence": 75,
        "recommended_next_action": "investigate_website",
    }
    result.update(overrides)
    return result


def make_lead(**overrides):
    lead = {
        "company_name": "Example Fresh Imports",
        "website": "https://example.com",
        "source_url": "https://example.com",
        "description": (
            "We import fresh oranges and grapes from international "
            "suppliers for wholesale distribution."
        ),
        "industry": "Fresh Produce Importer/Wholesaler",
        "products": ["oranges", "grapes"],
        "country": "Netherlands",
    }
    lead.update(overrides)
    return lead


def mock_ollama_response(qualification):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {
            "content": json.dumps(qualification)
        }
    }
    return response


@patch("app.local_ai_qualifier.requests.post")
def test_valid_importer_response(mock_post):
    mock_post.return_value = mock_ollama_response(make_qualification())

    result = qualify_lead(make_lead())

    assert result["buyer_status"] == "potential_buyer"
    assert result["buyer_type"] == "importer"
    assert result["confidence"] == 75
    mock_post.assert_called_once()


@patch("app.local_ai_qualifier.requests.post")
def test_exporter_only_is_not_automatically_a_buyer(mock_post):
    mock_post.return_value = mock_ollama_response(
        make_qualification(
            description="",
            buyer_status="potential_buyer",
            buyer_type="exporter",
            confidence=90,
        )
    )

    lead = make_lead(
        description=(
            "We grow and export our own fresh oranges. "
            "We do not purchase produce from other suppliers."
        ),
        industry="Fresh Produce Exporter",
        country="Egypt",
    )

    result = qualify_lead(lead)

    assert result["buyer_status"] == "uncertain"
    assert result["buyer_type"] == "unknown"
    assert result["confidence"] <= 40
    assert result["recommended_next_action"] == "investigate_website"


@patch("app.local_ai_qualifier.requests.post")
def test_invalid_json_retries_once(mock_post):
    first_response = Mock()
    first_response.raise_for_status.return_value = None
    first_response.json.return_value = {
        "message": {"content": "not valid JSON"}
    }

    expected = make_qualification()
    mock_post.side_effect = [
        first_response,
        mock_ollama_response(expected),
    ]

    result = qualify_lead(make_lead())

    assert result["buyer_status"] == "potential_buyer"
    assert mock_post.call_count == 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("buyer_status", "unknown_status", "Invalid buyer_status"),
        ("buyer_type", "unknown_type", "Invalid buyer_type"),
        (
            "recommended_next_action",
            "send_email",
            "Invalid recommended_next_action",
        ),
        ("confidence", 101, "confidence must be between 0 and 100"),
        ("confidence", True, "confidence must be an integer"),
        ("is_company", "yes", "is_company must be a boolean"),
        ("products_of_interest", "oranges", "must be a list"),
        ("evidence", [123], "Evidence items must be strings"),
    ],
)
@patch("app.local_ai_qualifier.requests.post")
def test_invalid_fields_are_rejected(
    mock_post, field, value, message
):
    response_data = make_qualification(**{field: value})
    mock_post.return_value = mock_ollama_response(response_data)

    with pytest.raises(ValueError, match=message):
        qualify_lead(make_lead())


@patch("app.local_ai_qualifier.requests.post")
def test_outreach_approval_is_never_returned(mock_post):
    mock_post.return_value = mock_ollama_response(
        make_qualification(
            recommended_next_action="consider_for_outreach"
        )
    )

    result = qualify_lead(make_lead())

    assert result["recommended_next_action"] == "investigate_website"


@patch("app.local_ai_qualifier.requests.post")
def test_missing_required_field_is_rejected(mock_post):
    qualification = make_qualification()
    del qualification["evidence"]
    mock_post.return_value = mock_ollama_response(qualification)

    with pytest.raises(ValueError, match="missing required fields"):
        qualify_lead(make_lead())

