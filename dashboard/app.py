import sys
import json
from pathlib import Path

import pandas as pd
import streamlit as st

# --------------------------------------------------
# PROJECT IMPORTS
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import database as database_module
from app.database import (
    get_all_leads,
    save_ai_qualification,
    normalize_website,
)
from app.local_ai_qualifier import qualify_lead
from app.discovery import discover_leads
from app.pipeline import process_website


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="EGAST AI Sales Agent",
    page_icon="🍊",
    layout="wide",
)

st.title("🍊 EGAST AI Sales Agent")
st.caption(
    "Discover, qualify, and prioritize potential fresh-produce buyers."
)

TARGET_NEW_LEADS_PER_RUN = 10
MAX_SEARCH_QUERIES = 10
RESULTS_PER_QUERY = 20
MAX_CANDIDATES_PER_RUN = 100


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def display_value(value, fallback="Not available"):
    """Display missing database values cleanly."""
    if value is None:
        return fallback

    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass

    value = str(value).strip()

    if not value or value.lower() in {"nan", "none", "null"}:
        return fallback

    return value


def is_missing(value):
    """Return True when a value is missing."""
    return display_value(value, fallback="") == ""


def load_leads():
    """Load the saved leads from the database."""
    records = get_all_leads()
    data = pd.DataFrame(records)

    if data.empty:
        return data

    expected_columns = [
        "id",
        "company_name",
        "country",
        "industry",
        "website",
        "email",
        "score",
        "buyer_status",
        "buyer_type",
        "products_of_interest",
        "target_country",
        "ai_evidence",
        "qualification_reason",
        "ai_confidence",
        "recommended_next_action",
        "ai_qualification_error",
    ]

    for column in expected_columns:
        if column not in data.columns:
            data[column] = None

    data["score"] = pd.to_numeric(
        data["score"], errors="coerce"
    ).fillna(0)

    data["ai_confidence"] = pd.to_numeric(
        data["ai_confidence"], errors="coerce"
    )

    return data


def get_saved_domains(records):
    """Return normalized website identifiers for saved records."""
    domains = set()

    for record in records:
        website = str(record.get("website") or "").strip()

        if not website:
            continue

        normalized = normalize_website(website)

        if normalized:
            domains.add(normalized)

    return domains


def extract_url(result):
    """Support discovery results represented as strings or dictionaries."""
    if isinstance(result, str):
        return result.strip()

    if isinstance(result, dict):
        value = (
            result.get("url")
            or result.get("link")
            or result.get("href")
        )

        if isinstance(value, str):
            return value.strip()

    return ""


# --------------------------------------------------
# INCREMENTAL DISCOVERY
# --------------------------------------------------

def run_incremental_discovery():
    """Run discovery quietly and return a concise summary for the dashboard."""
    saved_before = get_all_leads()
    before_count = len(saved_before)
    known_domains = get_saved_domains(saved_before)

    search_results = discover_leads(
        max_queries=MAX_SEARCH_QUERIES,
        results_per_query=RESULTS_PER_QUERY,
        max_results=MAX_CANDIDATES_PER_RUN,
        exclude_domains=known_domains,
    ) or []

    candidate_urls = []
    seen_domains = set(known_domains)

    for result in search_results:
        url = extract_url(result)
        if not url:
            continue

        domain = normalize_website(url)
        if not domain or domain in seen_domains:
            continue

        seen_domains.add(domain)
        candidate_urls.append(url)

        if len(candidate_urls) >= MAX_CANDIDATES_PER_RUN:
            break

    processed = 0
    failed = 0

    for url in candidate_urls:
        try:
            result = process_website(url)
            if isinstance(result, dict) and result.get("error"):
                failed += 1
            else:
                processed += 1
        except Exception:
            # Keep technical details out of the employee-facing dashboard.
            failed += 1

        current_records = get_all_leads()
        new_domains = get_saved_domains(current_records) - known_domains

        if len(new_domains) >= TARGET_NEW_LEADS_PER_RUN:
            break

    saved_after = get_all_leads()
    after_count = len(saved_after)
    new_domains = get_saved_domains(saved_after) - known_domains

    return {
        "processed": processed,
        "failed": failed,
        "before": before_count,
        "after": after_count,
        "new_rows": after_count - before_count,
        "new_leads": len(new_domains),
        "target": TARGET_NEW_LEADS_PER_RUN,
    }

# --------------------------------------------------
# DASHBOARD CONTROLS
# --------------------------------------------------

control_col1, control_col2 = st.columns([1, 2])

with control_col1:
    if st.button(
        "🔄 Refresh Dashboard",
        use_container_width=True,
    ):
        st.rerun()

with control_col2:
    if st.button(
        "🍊 Discover New Leads",
        type="primary",
        use_container_width=True,
    ):
        try:
            with st.spinner("Please wait..."):
                result = run_incremental_discovery()

            if result["new_leads"] > 0:
                st.success(f"{result['new_leads']} new lead(s) added successfully.")
            else:
                st.info("No new leads were added this time.")
        except Exception:
            # Avoid exposing technical errors or pipeline details to employees.
            st.error("We couldn't add new leads right now. Please try again later.")

        # Reload the dashboard so the lead count reflects the latest database.
        st.rerun()


# --------------------------------------------------
# LOAD CURRENT DATA
# --------------------------------------------------


df = load_leads()

# Display the exported leads when the cloud database is empty.
if df.empty:
    export_path = Path(__file__).resolve().parent / "egast_leads_export.csv"

    if export_path.exists():
        df = pd.read_csv(export_path)

        # Ensure the dashboard has all expected columns.
        expected_columns = [
            "id", "company_name", "country", "industry", "website",
            "email", "score", "buyer_status", "buyer_type",
            "products_of_interest", "target_country", "ai_evidence",
            "qualification_reason", "ai_confidence",
            "recommended_next_action", "ai_qualification_error",
        ]

        for column in expected_columns:
            if column not in df.columns:
                df[column] = None

        df["score"] = pd.to_numeric(
            df["score"], errors="coerce"
        ).fillna(0)

        df["ai_confidence"] = pd.to_numeric(
            df["ai_confidence"], errors="coerce"
        )

    else:
        st.info("No leads found yet. Import your saved leads first.")
        st.stop()


# --------------------------------------------------
# LEAD QUALIFICATION — MAIN KPIs ONLY
# --------------------------------------------------

total_leads = len(df)

potential_buyers = int(
    (df["buyer_status"] == "potential_buyer").sum()
)

st.divider()
st.subheader("🤖 Lead Qualification")

col1, col2 = st.columns(2)

col1.metric(
    "Total Leads",
    total_leads,
)

col2.metric(
    "Potential Buyers",
    potential_buyers,
)


# --------------------------------------------------
# LEAD DIRECTORY AND FILTERS
# --------------------------------------------------


st.divider()
st.subheader("Lead Directory")

search_text = st.text_input(
    "Search companies, industries, emails, or countries"
)

industries = sorted(
    value
    for value in df["industry"].dropna().astype(str).unique()
    if value.strip() and value.lower() != "nan"
)

selected_industry = st.selectbox(
    "Filter by industry",
    ["All industries"] + industries,
)

buyer_statuses = [
    "All statuses",
    "potential_buyer",
    "uncertain",
    "not_buyer",
    "Not yet qualified",
    "AI Error",
]

selected_status = st.selectbox(
    "Filter by AI buyer status",
    buyer_statuses,
)

filtered = df.copy()

# Search by company, industry, email, or country
if search_text.strip():
    searchable = (
        filtered["company_name"].fillna("").astype(str)
        + " "
        + filtered["industry"].fillna("").astype(str)
        + " "
        + filtered["email"].fillna("").astype(str)
        + " "
        + filtered["country"].fillna("").astype(str)
    )

    filtered = filtered[
        searchable.str.contains(
            search_text.strip(),
            case=False,
            regex=False,
        )
    ]

# Filter by industry
if selected_industry != "All industries":
    filtered = filtered[
        filtered["industry"] == selected_industry
    ]

# Filter by AI buyer status
if selected_status == "Not yet qualified":
    filtered = filtered[
        filtered["buyer_status"].apply(is_missing)
        & filtered["ai_qualification_error"].apply(is_missing)
    ]

elif selected_status == "AI Error":
    filtered = filtered[
        ~filtered["ai_qualification_error"].apply(is_missing)
    ]

elif selected_status != "All statuses":
    filtered = filtered[
        filtered["buyer_status"] == selected_status
    ]

# Show highest-scoring leads first
filtered = filtered.sort_values(
    "score",
    ascending=False,
)

display_columns = [
    column
    for column in [
        "company_name",
        "country",
        "industry",
        "website",
        "email",
        "buyer_status",
        "buyer_type",
        "recommended_next_action",
    ]
    if column in filtered.columns
]

table_df = filtered[display_columns].copy()

for column in [
    "company_name",
    "country",
    "industry",
    "website",
    "email",
    "buyer_status",
    "buyer_type",
    "recommended_next_action",
]:
    if column in table_df.columns:
        table_df[column] = table_df[column].apply(
            lambda value: display_value(value, "")
        )

st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "company_name": "Company",
        "country": "Country",
        "industry": "Industry",
        "website": st.column_config.LinkColumn("Website"),
        "email": "Email",
        "buyer_status": "AI Buyer Status",
        "buyer_type": "Buyer Type",
        "recommended_next_action": "Recommended Action",
    },
)

st.caption(
    f"Showing {len(filtered)} of {len(df)} saved leads."
)