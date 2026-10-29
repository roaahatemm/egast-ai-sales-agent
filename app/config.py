
import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the project's .env file
load_dotenv(BASE_DIR / ".env")

# Company profile
PROFILE_PATH = BASE_DIR / "egast_profile.json"


def load_company_profile() -> dict:
    """Load and validate the EGAST company profile."""
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Company profile not found: {PROFILE_PATH}"
        )

    with PROFILE_PATH.open("r", encoding="utf-8") as file:
        profile = json.load(file)

    if not profile.get("company_name"):
        raise ValueError("The company profile needs a company_name.")

    if not isinstance(profile.get("products"), list):
        raise ValueError("The products field must be a list.")

    return profile


# Optional API settings; we'll configure these later.
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
