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

MAX_NEW_WEBSITES_PER_RUN = 10
MAX_SEARCH_QUERIES = 3
RESULTS_PER_QUERY = 10


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
    """
    Discover and process at most 10 new website candidates.

    Reports candidate counts and actual database row counts so
    we can distinguish discovery failures from save failures.
    """

    saved_before = get_all_leads()
    before_count = len(saved_before)
    known_domains = get_saved_domains(saved_before)

    st.write(f"**Saved leads before discovery:** {before_count}")

    db_path = getattr(
        database_module,
        "DATABASE_PATH",
        "Database path not exposed by app.database",
    )
    st.write(f"**Database path:** `{db_path}`")

    st.write(
        f"Searching up to {MAX_SEARCH_QUERIES} queries for "
        f"a maximum of {MAX_NEW_WEBSITES_PER_RUN} new websites..."
    )

    # This requires the updated app/discovery.py to accept these arguments.
    search_results = discover_leads(
        max_queries=MAX_SEARCH_QUERIES,
        results_per_query=RESULTS_PER_QUERY,
        max_results=MAX_NEW_WEBSITES_PER_RUN,
        exclude_domains=known_domains,
    ) or []

    st.write(
        f"**Candidate results returned:** {len(search_results)}"
    )

    with st.expander("Inspect discovery results"):
        st.json(search_results[:5])

    new_urls = []
    seen_domains = set()

    for result in search_results:
        url = extract_url(result)

        if not url:
            continue

        domain = normalize_website(url)

        if not domain:
            continue

        if domain in known_domains or domain in seen_domains:
            continue

        seen_domains.add(domain)
        new_urls.append(url)

        if len(new_urls) >= MAX_NEW_WEBSITES_PER_RUN:
            break

    st.write(
        f"**New websites after duplicate filtering:** {len(new_urls)}"
    )

    if not new_urls:
        saved_after = get_all_leads()
        after_count = len(saved_after)

        st.write(f"**Saved leads after discovery:** {after_count}")
        st.write(
            f"**Change in database row count:** "
            f"{after_count - before_count}"
        )

        return {
            "processed": 0,
            "failed": 0,
            "candidates": len(search_results),
            "before": before_count,
            "after": after_count,
            "new_rows": after_count - before_count,
        }

    progress = st.progress(0)
    status = st.empty()

    processed = 0
    failed = 0

    for index, url in enumerate(new_urls, start=1):
        status.write(
            f"Processing website {index}/{len(new_urls)}: {url}"
        )

        try:
            # Existing pipeline handles scraping, extraction,
            # scoring, saving and AI qualification.
            process_website(url)
            processed += 1

        except Exception as exc:
            failed += 1
            st.warning(
                f"Failed to process {url}: "
                f"{type(exc).__name__}: {exc}"
            )

        progress.progress(index / len(new_urls))

    # Re-read the database to verify whether records were saved.
    saved_after = get_all_leads()
    after_count = len(saved_after)
    new_rows = after_count - before_count

    status.write("Discovery batch finished.")

    st.write(f"**Websites processed without an exception:** {processed}")
    st.write(f"**Processing failures:** {failed}")
    st.write(f"**Saved leads before:** {before_count}")
    st.write(f"**Saved leads after:** {after_count}")
    st.write(f"**Net change in database rows:** {new_rows}")

    if new_rows <= 0 and processed > 0:
        st.warning(
            "Websites were processed, but the total database row count "
            "did not increase. The pipeline may have updated existing "
            "records, rejected extracted websites, or saved to a different "
            "database. Check the terminal output and save_lead() logic."
        )

    return {
        "processed": processed,
        "failed": failed,
        "candidates": len(search_results),
        "before": before_count,
        "after": after_count,
        "new_rows": new_rows,
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
            with st.spinner("Discovering new websites..."):
                result = run_incremental_discovery()

            st.success(
                f"Batch finished. Processed: {result['processed']}; "
                f"failures: {result['failed']}; "
                f"database rows: {result['before']} → {result['after']}."
            )

            if result["new_rows"] <= 0:
                st.info(
                    "No net increase in saved leads. Review the diagnostic "
                    "numbers above to identify where the process stopped."
                )

        except Exception as exc:
            st.error(
                f"Discovery failed: {type(exc).__name__}: {exc}"
            )

        # Reload the UI from the database after processing.
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
        "score",
        "buyer_status",
        "buyer_type",
        "ai_confidence",
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
        "score": st.column_config.NumberColumn(
            "Lead Score",
            min_value=0,
            max_value=100,
            format="%d/100",
        ),
        "buyer_status": "AI Buyer Status",
        "buyer_type": "Buyer Type",
        "ai_confidence": st.column_config.NumberColumn(
            "AI Confidence",
            min_value=0,
            max_value=100,
            format="%d%%",
        ),
        "recommended_next_action": "Recommended Action",
    },
)

st.caption(
    f"Showing {len(filtered)} of {len(df)} saved leads."
)