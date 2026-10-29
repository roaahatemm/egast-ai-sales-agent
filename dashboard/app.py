
import sys
import json
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow imports from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_all_leads, save_ai_qualification
from app.local_ai_qualifier import qualify_lead


# --------------------------------------------------
# PAGE CONFIGURATION
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


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def display_value(value, fallback="Not available"):
    """Display missing database values cleanly."""
    if value is None or pd.isna(value):
        return fallback

    value = str(value).strip()

    if not value or value.lower() in {"nan", "none", "null"}:
        return fallback

    return value


def is_missing(value):
    """Return True if a database value is empty or missing."""
    return display_value(value, fallback="") == ""


def load_leads():
    """Load saved leads without changing the database."""
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


# --------------------------------------------------
# LOAD SAVED LEADS
# --------------------------------------------------

df = load_leads()

if df.empty:
    st.info(
        "No leads found yet. Run the discovery pipeline to add leads."
    )
    st.stop()


# --------------------------------------------------
# AI QUALIFICATION CONTROLS
# --------------------------------------------------

st.subheader("🤖 AI Lead Qualification")

st.write(
    "Use the local AI model to assess existing leads. "
    "This does not run website discovery."
)

unqualified_mask = (
    df["buyer_status"].apply(is_missing)
    & df["ai_qualification_error"].apply(is_missing)
)

unqualified_count = int(unqualified_mask.sum())

st.write(
    f"**Leads awaiting qualification:** {unqualified_count}"
)

batch_size = st.selectbox(
    "Number of leads to qualify",
    options=[1, 5],
    index=1,
    help="Start with five leads to test the results before processing more.",
)

if unqualified_count > 0:
    if st.button(
        f"Qualify next {min(batch_size, unqualified_count)} leads",
        type="primary",
        use_container_width=False,
    ):
        # Select existing records that have no saved AI status
        # and no previous AI error.
        pending = df.loc[unqualified_mask].head(batch_size)

        progress = st.progress(0)
        status_text = st.empty()

        successful = 0
        failed = 0

        for index, (_, row) in enumerate(pending.iterrows(), start=1):
            lead_id = row["id"]
            company_name = display_value(
                row.get("company_name"), f"Lead {lead_id}"
            )

            status_text.write(
                f"Qualifying {index}/{len(pending)}: {company_name}"
            )

            # Pass the saved lead to the AI without scraping
            # or discovering the website again.
            lead_for_ai = row.to_dict()

            try:
                qualification = qualify_lead(lead_for_ai)

                save_ai_qualification(
                    lead_id,
                    qualification=qualification,
                )

                successful += 1

            except Exception as exc:
                error_message = f"{type(exc).__name__}: {exc}"

                try:
                    save_ai_qualification(
                        lead_id,
                        error=error_message,
                    )
                except Exception as db_exc:
                    st.error(
                        f"Could not save the error for "
                        f"{company_name}: {db_exc}"
                    )

                failed += 1
                st.warning(
                    f"AI qualification failed for {company_name}: "
                    f"{error_message}"
                )

            progress.progress(index / len(pending))

        status_text.write("Batch finished.")

        st.success(
            f"Batch complete. Successful: {successful}. "
            f"Failed: {failed}."
        )

        st.rerun()

elif df["ai_qualification_error"].apply(is_missing).sum() == 0:
    st.success("All saved leads have an AI qualification status.")

else:
    st.info(
        "No unqualified leads without errors remain. "
        "Review the AI Errors section below before retrying failed leads."
    )


# --------------------------------------------------
# REFRESH DATA AFTER QUALIFICATION
# --------------------------------------------------

df = load_leads()

if df.empty:
    st.info("No leads found.")
    st.stop()


# --------------------------------------------------
# MAIN KPI METRICS
# --------------------------------------------------

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Leads", len(df))

col2.metric(
    "High-Priority Leads",
    int((df["score"] >= 70).sum()),
)

col3.metric(
    "Leads with Email",
    int(
        df["email"].fillna("").astype(str)
        .str.strip().ne("").sum()
    ),
)

col4.metric(
    "Average Score",
    f"{df['score'].mean():.0f}/100",
)


# --------------------------------------------------
# AI QUALIFICATION OVERVIEW
# --------------------------------------------------

st.divider()
st.subheader("AI Qualification Overview")

has_status = ~df["buyer_status"].apply(is_missing)

potential_buyers = int(
    (df["buyer_status"] == "potential_buyer").sum()
)

needs_review = int(
    (df["buyer_status"] == "uncertain").sum()
)

not_buyers = int(
    (df["buyer_status"] == "not_buyer").sum()
)

ai_errors = int(
    (~df["ai_qualification_error"].apply(is_missing)).sum()
)

qualified_count = int(has_status.sum())

ai_col1, ai_col2, ai_col3, ai_col4, ai_col5 = st.columns(5)

ai_col1.metric("AI Qualified", qualified_count)
ai_col2.metric("Potential Buyers", potential_buyers)
ai_col3.metric("Needs Review", needs_review)
ai_col4.metric("Not Buyers", not_buyers)
ai_col5.metric("AI Errors", ai_errors)

not_yet_qualified = int(
    (
        df["buyer_status"].apply(is_missing)
        & df["ai_qualification_error"].apply(is_missing)
    ).sum()
)

st.caption(
    f"{not_yet_qualified} leads have not yet received "
    "a saved AI qualification and have no recorded AI error."
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

min_score = st.slider(
    "Minimum lead score",
    min_value=0,
    max_value=100,
    value=0,
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

if selected_industry != "All industries":
    filtered = filtered[
        filtered["industry"] == selected_industry
    ]

filtered = filtered[filtered["score"] >= min_score]

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

filtered = filtered.sort_values(
    "score",
    ascending=False,
)

# Prepare the display so missing values appear as readable text.
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


# --------------------------------------------------
# LEAD QUALIFICATION DETAILS
# --------------------------------------------------

st.divider()
st.subheader("🔎 Lead Qualification Details")

company_options = {
    f"{display_value(row.get('company_name'), 'Unnamed company')} "
    f"(ID: {row['id']})": row["id"]
    for _, row in df.iterrows()
}

if company_options:
    selected_company = st.selectbox(
        "Select a lead to inspect",
        list(company_options.keys()),
    )

    selected_id = company_options[selected_company]
    selected_rows = df[df["id"] == selected_id]

    if not selected_rows.empty:
        lead = selected_rows.iloc[0]

        detail_col1, detail_col2 = st.columns(2)

        with detail_col1:
            st.write(
                "**Company:**",
                display_value(lead.get("company_name")),
            )

            st.write(
                "**Buyer status:**",
                display_value(
                    lead.get("buyer_status"),
                    "Not yet qualified",
                ),
            )

            st.write(
                "**Buyer type:**",
                display_value(lead.get("buyer_type")),
            )

            confidence = lead.get("ai_confidence")

            st.write(
                "**AI confidence:**",
                f"{int(confidence)}%"
                if pd.notna(confidence)
                else "Not available",
            )

        with detail_col2:
            target_country = lead.get("target_country")

            if is_missing(target_country):
                target_country = lead.get("country")

            st.write(
                "**Target country:**",
                display_value(target_country),
            )

            st.write(
                "**Recommended action:**",
                display_value(lead.get("recommended_next_action")),
            )

            st.write(
                "**Products of interest:**",
                display_value(lead.get("products_of_interest")),
            )

        reason = lead.get("qualification_reason")

        if not is_missing(reason):
            st.write("**Qualification reason**")
            st.write(reason)

        evidence = lead.get("ai_evidence")

        if not is_missing(evidence):
            st.write("**Evidence supplied by the AI**")

            try:
                evidence_items = json.loads(evidence)

                if isinstance(evidence_items, list):
                    for item in evidence_items:
                        st.markdown(f"- {item}")
                else:
                    st.write(evidence)

            except (json.JSONDecodeError, TypeError):
                st.write(evidence)

        ai_error = lead.get("ai_qualification_error")

        if not is_missing(ai_error):
            st.warning(f"AI qualification error: {ai_error}")

        website = lead.get("website")

        if not is_missing(website):
            st.write("**Website:**", display_value(website))

