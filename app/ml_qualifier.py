
"""Advisory ML classification for EGAST sales leads."""

from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd


MODEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "training"
    / "lead_classifier_v2.joblib"
)


def _clean(value, limit=1500):
    """Convert lead fields to readable text consistently."""
    if value is None:
        return ""

    if isinstance(value, (list, dict)):
        import json
        value = json.dumps(value, ensure_ascii=False)

    return str(value).strip()[:limit]


@lru_cache(maxsize=1)
def _load_artifact():
    """Load the trained model once per application process."""
    if not MODEL_PATH.exists():
        return None

    artifact = joblib.load(MODEL_PATH)

    if not isinstance(artifact, dict) or "model" not in artifact:
        raise ValueError("Invalid ML model artifact.")

    return artifact


def predict_buyer(lead: dict) -> dict:
    """
    Return an advisory ML prediction.

    This prediction must not automatically reject a lead or authorize
    outreach. Missing model files produce an unavailable result.
    """
    if not isinstance(lead, dict):
        raise TypeError("lead must be a dictionary.")

    try:
        artifact = _load_artifact()
    except Exception as exc:
        return {
            "available": False,
            "error": f"Could not load ML model: {type(exc).__name__}: {exc}",
        }

    if artifact is None:
        return {
            "available": False,
            "error": f"ML model not found: {MODEL_PATH}",
        }

    features = artifact.get("features", [])
    if not features:
        return {
            "available": False,
            "error": "ML artifact has no feature definitions.",
        }

    # Match the text construction used by the training script.
    row = {
        feature: _clean(lead.get(feature))
        for feature in features
    }

    text_parts = []
    for feature in features:
        value = row[feature]
        if pd.notna(value) and str(value).strip():
            text_parts.append(f"{feature}: {str(value).strip()}")

    model_input = [" | ".join(text_parts)]
    model = artifact["model"]

    try:
        probabilities = model.predict_proba(model_input)[0]
        classes = list(model.named_steps["classifier"].classes_)
        class_probabilities = dict(zip(classes, probabilities))

        buyer_probability = float(
            class_probabilities.get("potential_buyer", 0.0)
        )
        threshold = float(artifact.get("threshold", 0.65))

        if buyer_probability >= threshold:
            prediction = "potential_buyer"
        elif buyer_probability <= 1 - threshold:
            prediction = "not_buyer"
        else:
            prediction = "uncertain"

        return {
            "available": True,
            "prediction": prediction,
            "buyer_probability": round(buyer_probability, 4),
            "threshold": threshold,
            "model_version": "lead_classifier_v2",
            "advisory_only": True,
        }

    except Exception as exc:
        return {
            "available": False,
            "error": f"ML prediction failed: {type(exc).__name__}: {exc}",
        }
