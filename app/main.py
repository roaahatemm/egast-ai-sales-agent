import sqlite3
from urllib.parse import urlsplit
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from app.discovery import discover_leads
from app.pipeline import process_website
from app.database import (
    DATABASE_PATH,
    initialize_database,
    get_all_leads,
)


EMPLOYEES = [
    "Walaa",
    "Basma",
    "Badr",
    "Nancy",
    "Deghedy",
    "Sohaila",
    "Mohamed",
    "Aya",
]


# =========================================================
# DATABASE: EMPLOYEE ASSIGNMENTS
# =========================================================

def initialize_assignments():
    """Create a persistent table for employee-to-lead assignments."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_assignments (
                lead_id INTEGER PRIMARY KEY,
                employee_name TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_notes (
                lead_id INTEGER PRIMARY KEY,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            )
            """
        )


def get_assignments():
    """Return all current lead assignments."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT lead_id, employee_name, assigned_at, updated_at
            FROM lead_assignments
            """
        ).fetchall()

    return [dict(row) for row in rows]


def assign_lead(lead_id: int, employee_name: str):
    """Assign a lead to one employee, replacing any previous assignment."""
    if employee_name not in EMPLOYEES:
        raise ValueError("Select a valid employee.")

    now = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DATABASE_PATH) as connection:
        lead_exists = connection.execute(
            "SELECT 1 FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()

        if not lead_exists:
            raise ValueError("This lead does not exist in the database.")

        connection.execute(
            """
            INSERT INTO lead_assignments (
                lead_id, employee_name, assigned_at, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(lead_id) DO UPDATE SET
                employee_name = excluded.employee_name,
                updated_at = excluded.updated_at
            """,
            (lead_id, employee_name, now, now),
        )


def remove_assignment(lead_id: int):
    """Remove an assignment without deleting the saved company."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "DELETE FROM lead_assignments WHERE lead_id = ?",
            (lead_id,),
        )


def get_saved_leads_with_assignments():
    """Load saved leads and their latest assignments directly from SQLite."""
    leads = get_all_leads()
    if not leads:
        return pd.DataFrame()

    df = pd.DataFrame(leads)
    if "id" not in df.columns:
        raise ValueError("The leads data must contain an 'id' column.")

    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    df = df.dropna(subset=["id"]).copy()
    df["id"] = df["id"].astype("int64")
    # Avoid duplicate/stale assignment columns before merging.
    df = df.drop(columns=["employee_name", "lead_id"], errors="ignore")

    with sqlite3.connect(DATABASE_PATH) as connection:
        assignments = pd.read_sql_query(
            "SELECT lead_id, employee_name FROM lead_assignments",
            connection,
        )

    if not assignments.empty:
        assignments["lead_id"] = pd.to_numeric(
            assignments["lead_id"], errors="coerce"
        )
        assignments = assignments.dropna(subset=["lead_id"]).copy()
        assignments["lead_id"] = assignments["lead_id"].astype("int64")
        assignments = assignments.drop_duplicates(subset=["lead_id"], keep="last")
        df = df.merge(
            assignments,
            left_on="id",
            right_on="lead_id",
            how="left",
            validate="one_to_one",
        ).drop(columns=["lead_id"], errors="ignore")
    else:
        df["employee_name"] = None

    df["employee_name"] = df["employee_name"].fillna("Unassigned").astype(str)
    return df


def get_lead_notes():
    """Return saved personal notes keyed by lead ID."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            "SELECT lead_id, note FROM lead_notes"
        ).fetchall()
    return {int(lead_id): note for lead_id, note in rows}


def save_lead_note(lead_id: int, note: str):
    """Insert or update a lead's personal note."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        exists = connection.execute(
            "SELECT 1 FROM leads WHERE id = ?", (int(lead_id),)
        ).fetchone()
        if not exists:
            raise ValueError("This lead does not exist in the database.")
        connection.execute(
            """INSERT INTO lead_notes (lead_id, note, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(lead_id) DO UPDATE SET
                   note = excluded.note,
                   updated_at = excluded.updated_at""",
            (int(lead_id), note.strip(), now),
        )


def delete_lead(lead_id: int):
    """Delete a lead and its assignment/note records."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        exists = connection.execute(
            "SELECT 1 FROM leads WHERE id = ?", (int(lead_id),)
        ).fetchone()
        if not exists:
            raise ValueError("This lead does not exist in the database.")
        connection.execute("DELETE FROM lead_assignments WHERE lead_id = ?", (int(lead_id),))
        connection.execute("DELETE FROM lead_notes WHERE lead_id = ?", (int(lead_id),))
        connection.execute("DELETE FROM leads WHERE id = ?", (int(lead_id),))


# =========================================================
# DISCOVERY: NORMALIZE DOMAINS AND FILTER DUPLICATES
# =========================================================

def normalize_domain(url: str) -> str:
    """
    Normalize a website hostname for duplicate detection.

    Examples:
        https://www.example.com/ -> example.com
        https://example.com/about -> example.com
    """
    if not url:
        return ""

    try:
        value = url.strip()

        parsed = urlsplit(
            value if "://" in value else f"https://{value}"
        )

        hostname = (parsed.hostname or "").lower().rstrip(".")

        if hostname.startswith("www."):
            hostname = hostname[4:]

        return hostname

    except (ValueError, AttributeError):
        return ""


def filter_new_results(results):
    """
    Exclude domains already saved in the database and duplicates
    within the current discovery batch.
    """
    saved_leads = get_all_leads()

    saved_domains = set()
    for lead in saved_leads:
        # The database may store the website with or without a scheme/www.
        saved_url = (
            lead.get("website")
            or lead.get("source_url")
            or lead.get("url")
            or ""
        )
        domain = normalize_domain(saved_url)
        if domain:
            saved_domains.add(domain)

    seen_domains = set()
    new_results = []

    for result in results or []:
        if not isinstance(result, dict):
            continue

        url = (result.get("url") or "").strip()
        domain = normalize_domain(url)

        if not domain:
            continue

        if domain in saved_domains:
            continue

        if domain in seen_domains:
            continue

        seen_domains.add(domain)
        new_results.append(result)

    return new_results


# =========================================================
# TAB 1: DISCOVER BUYERS
# =========================================================

def show_discover_buyers():
    st.header("Discover Potential Buyers")

    st.write(
        "Find potential importers, distributors, and buyers "
        "for EGAST's fresh produce."
    )

    if st.button(
        "Start Buyer Discovery",
        type="primary",
        key="discover_button",
    ):
        try:
            with st.spinner("Searching for new potential buyers..."):
                raw_results = discover_leads(
                    max_queries=5,
                    results_per_query=20,
                    max_results=100,
                )

            # Always compare search results with the current database.
            # This prevents previously processed websites from appearing
            # again when the discovery button is clicked.
            results = filter_new_results(raw_results)

            st.session_state["discovered_results"] = results
            st.session_state["processed_urls"] = []

            st.success(
                f"Search returned {len(raw_results or [])} results. "
                f"Found {len(results)} new unique websites after "
                "excluding all currently saved companies and duplicates."
            )

        except Exception as error:
            st.error(
                f"Discovery failed: {type(error).__name__}: {error}"
            )

    results = st.session_state.get("discovered_results", [])

    if not results:
        st.info(
            "Click Start Buyer Discovery to find new companies. "
            "If no new results appear, the search may only be returning "
            "websites already saved in the database."
        )
        return

    st.divider()
    st.subheader(f"Discovery Results ({len(results)})")

    st.info(
        "Search results are not saved leads until processed. "
        "Processing extracts company details, runs ML and Ollama "
        "qualification, and saves the company in the database."
    )

    processed_urls = set(
        st.session_state.get("processed_urls", [])
    )

    # Process and save every result.
    if st.button(
        "Process & Save All Discovered Companies",
        type="primary",
        key="process_all_button",
    ):
        total = len(results)
        progress = st.progress(0)
        status = st.empty()

        succeeded = 0
        failed = 0

        for index, result in enumerate(results):
            url = (result.get("url") or "").strip()

            if not url or url in processed_urls:
                progress.progress((index + 1) / total)
                continue

            status.write(
                f"Processing {index + 1}/{total}: {url}"
            )

            try:
                lead = process_website(url)

                if lead.get("id") and not lead.get("error"):
                    # Confirm the pipeline actually persisted this website.
                    saved_domains = {
                        normalize_domain(
                            item.get("website")
                            or item.get("source_url")
                            or item.get("url")
                            or ""
                        )
                        for item in get_all_leads()
                    }
                    if normalize_domain(url) in saved_domains:
                        processed_urls.add(url)
                        succeeded += 1
                    else:
                        failed += 1
                        st.warning(
                            f"{url} was processed, but it was not found "
                            "in the saved leads database."
                        )
                else:
                    failed += 1

            except Exception as error:
                failed += 1
                st.warning(f"Could not process {url}: {error}")

            progress.progress((index + 1) / total)

        st.session_state["processed_urls"] = list(processed_urls)

        status.empty()

        # Clear the old discovery batch. The Saved Leads tab will re-read
        # the database on rerun, and the next discovery run will exclude
        # everything just saved.
        st.session_state.pop("discovered_results", None)
        st.session_state.pop("processed_urls", None)

        st.success(
            f"Completed. Saved and verified: {succeeded}. "
            f"Failed: {failed}. "
            f"Current saved lead count: {len(get_all_leads())}."
        )

        st.rerun()

    st.divider()
    st.subheader("Individual Search Results")

    for index, result in enumerate(results):
        url = (result.get("url") or "").strip()

        title = (
            result.get("title")
            or result.get("company_name")
            or url
            or "Untitled result"
        )

        with st.container(border=True):
            st.markdown(f"**{title}**")

            if url:
                st.markdown(f"[{url}]({url})")

            if url in processed_urls:
                st.success("Processed during this session.")

            elif url:
                if st.button(
                    "Process & Save Lead",
                    key=f"process_lead_{index}",
                ):
                    try:
                        with st.spinner(f"Processing {title}..."):
                            lead = process_website(url)

                        if lead.get("error"):
                            st.error(lead["error"])

                        elif lead.get("id"):
                            saved_domains = {
                                normalize_domain(
                                    item.get("website")
                                    or item.get("source_url")
                                    or item.get("url")
                                    or ""
                                )
                                for item in get_all_leads()
                            }

                            if normalize_domain(url) not in saved_domains:
                                st.error(
                                    "The pipeline returned a lead ID, but "
                                    "the website was not found in the saved "
                                    "leads database."
                                )
                                st.stop()

                            processed_urls.add(url)
                            st.session_state["processed_urls"] = list(
                                processed_urls
                            )

                            st.success(
                                f"Lead processed and saved. "
                                f"Total saved leads: {len(get_all_leads())}."
                            )

                            with st.expander("View AI assessments"):
                                st.write(
                                    "Company",
                                    lead.get("company_name", "Unknown"),
                                )

                                st.write(
                                    "ML assessment",
                                    lead.get("ml_assessment", {}),
                                )

                                st.write(
                                    "Ollama assessment",
                                    lead.get("ai_qualification", {}),
                                )

                            st.rerun()

                        else:
                            st.warning(
                                "No lead ID was returned. "
                                "Check the pipeline output."
                            )

                    except Exception as error:
                        st.error(
                            f"Processing failed: "
                            f"{type(error).__name__}: {error}"
                        )


# =========================================================
# TAB 2: EMPLOYEES & ASSIGNMENTS
# =========================================================

def show_employee_assignments():
    st.header("Employees & Lead Assignments")

    st.write(
        "Assign every saved company to one employee. "
        "Assignments are stored in the database and persist "
        "when the app restarts."
    )

    df = get_saved_leads_with_assignments()

    if df.empty:
        st.info(
            "There are no saved leads yet. Discover and process "
            "companies before assigning them."
        )
        return

    assignments = get_assignments()

    if not assignments:
        assignment_counts = {}
    else:
        assignment_df = pd.DataFrame(assignments)

        assignment_counts = (
            assignment_df["employee_name"].value_counts().to_dict()
        )

    unassigned_count = int(
        (df["employee_name"] == "Unassigned").sum()
    )

    metric_columns = st.columns(3)

    metric_columns[0].metric("Saved Companies", len(df))
    metric_columns[1].metric("Assigned Companies", len(assignments))
    metric_columns[2].metric("Unassigned Companies", unassigned_count)

    st.divider()
    st.subheader("Employee Workload")

    workload = pd.DataFrame(
        [
            {
                "Employee": employee,
                "Assigned Leads": assignment_counts.get(employee, 0),
            }
            for employee in EMPLOYEES
        ]
    )

    st.dataframe(
        workload,
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.subheader("Assign or Reassign a Company")

    options = {
        (
            f"{row['id']} — "
            f"{row.get('company_name') or 'Unknown company'}"
        ): int(row["id"])
        for _, row in df.sort_values(
            "id", ascending=False
        ).iterrows()
    }

    selected_label = st.selectbox(
        "Choose a saved company",
        options=list(options.keys()),
        key="assignment_lead",
    )

    selected_lead_id = options[selected_label]

    current_assignment = next(
        (
            item["employee_name"]
            for item in assignments
            if item["lead_id"] == selected_lead_id
        ),
        None,
    )

    if current_assignment:
        st.info(f"Currently assigned to: {current_assignment}")
    else:
        st.info("This company is currently unassigned.")

    default_index = (
        EMPLOYEES.index(current_assignment)
        if current_assignment in EMPLOYEES
        else 0
    )

    selected_employee = st.selectbox(
        "Assign to employee",
        EMPLOYEES,
        index=default_index,
        key="assignment_employee",
    )

    col_assign, col_remove = st.columns(2)

    with col_assign:
        if st.button(
            "Save Assignment",
            type="primary",
            use_container_width=True,
        ):
            try:
                assign_lead(selected_lead_id, selected_employee)

                st.success(
                    f"Company assigned to {selected_employee}."
                )

                st.rerun()

            except Exception as error:
                st.error(
                    f"Assignment failed: "
                    f"{type(error).__name__}: {error}"
                )

    with col_remove:
        if st.button(
            "Remove Assignment",
            use_container_width=True,
        ):
            remove_assignment(selected_lead_id)

            st.success(
                "Assignment removed. The company remains saved."
            )

            st.rerun()

    st.divider()
    st.subheader("View an Employee's Leads")

    selected_filter = st.selectbox(
        "Employee",
        ["All employees", "Unassigned"] + EMPLOYEES,
        key="employee_filter",
    )

    if selected_filter == "Unassigned":
        filtered_df = df[df["employee_name"] == "Unassigned"]

    elif selected_filter == "All employees":
        filtered_df = df

    else:
        filtered_df = df[
            df["employee_name"] == selected_filter
        ]

    columns = [
        column
        for column in [
            "id",
            "company_name",
            "country",
            "industry",
            "website",
            "email",
            "buyer_status",
            "ml_buyer_prediction",
            "employee_name",
        ]
        if column in filtered_df.columns
    ]

    st.dataframe(
        filtered_df[columns],
        use_container_width=True,
        hide_index=True,
    )


# =========================================================
# TAB 3: SAVED LEADS
# =========================================================

def show_saved_leads():
    st.header("Saved Leads")
    st.caption("Search, review, assign, and manage your buyer pipeline.")

    df = get_saved_leads_with_assignments()  # Fresh SQLite read on every rerun.
    if df.empty:
        st.info("No saved leads yet. Go to Discover Buyers and process a company.")
        return

    message = st.session_state.pop("saved_leads_message", None)
    if message:
        st.success(message)
    error_message = st.session_state.pop("saved_leads_error", None)
    if error_message:
        st.error(error_message)

    notes_by_id = get_lead_notes()
    assigned_mask = ~df["employee_name"].fillna("Unassigned").str.strip().str.lower().isin(
        ["unassigned", "none", "nan", ""]
    )
    total_count = len(df)
    assigned_count = int(assigned_mask.sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Leads", f"{total_count:,}")
    c2.metric("Assigned", f"{assigned_count:,}")
    c3.metric("Unassigned", f"{total_count - assigned_count:,}")
    st.divider()

    search_col, assignment_col, employee_col = st.columns([2, 1, 1])
    with search_col:
        search = st.text_input(
            "Search leads", placeholder="Company, website, industry, country...",
            key="saved_leads_search",
        )
    with assignment_col:
        assignment_filter = st.selectbox(
            "Assignment", ["All", "Assigned", "Unassigned"],
            key="saved_leads_assignment_filter",
        )
    with employee_col:
        employee_filter = st.selectbox(
            "Employee", ["All"] + EMPLOYEES, key="saved_leads_employee_filter"
        )

    filtered = df.copy()
    if search.strip():
        search_cols = [c for c in ["company_name", "website", "industry", "country", "email"] if c in filtered.columns]
        mask = pd.Series(False, index=filtered.index)
        for column in search_cols:
            mask |= filtered[column].fillna("").astype(str).str.contains(search.strip(), case=False, regex=False)
        filtered = filtered[mask]

    filtered_assigned = ~filtered["employee_name"].fillna("Unassigned").str.strip().str.lower().isin(
        ["unassigned", "none", "nan", ""]
    )
    if assignment_filter == "Assigned":
        filtered = filtered[filtered_assigned]
    elif assignment_filter == "Unassigned":
        filtered = filtered[~filtered_assigned]
    if employee_filter != "All":
        filtered = filtered[filtered["employee_name"] == employee_filter]

    filtered = filtered.sort_values(
        "company_name", key=lambda s: s.fillna("").astype(str).str.lower()
    )
    st.caption(f"Showing {len(filtered):,} of {total_count:,} leads")

    # Compact table: score deliberately omitted; notes loaded from SQLite.
    table_cols = [c for c in [
        "id", "company_name", "country", "industry", "website", "email",
        "employee_name", "buyer_status"
    ] if c in filtered.columns]
    table_df = filtered[table_cols].copy()
    table_df["notes"] = table_df["id"].map(notes_by_id).fillna("")
    st.dataframe(
        table_df, use_container_width=True, hide_index=True, height=430,
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d", width="small"),
            "company_name": st.column_config.TextColumn("Company", width="medium"),
            "country": st.column_config.TextColumn("Country", width="small"),
            "industry": st.column_config.TextColumn("Industry", width="medium"),
            "website": st.column_config.LinkColumn("Website", width="medium"),
            "email": st.column_config.TextColumn("Email", width="medium"),
            "employee_name": st.column_config.TextColumn("Assigned Employee", width="small"),
            "buyer_status": st.column_config.TextColumn("Buyer Status", width="small"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
        },
    )

    export_df = df.copy()
    export_df["personal_notes"] = export_df["id"].map(notes_by_id).fillna("")
    export_cols = [c for c in [
        "id", "company_name", "country", "industry", "website", "email",
        "buyer_status", "employee_name", "personal_notes"
    ] if c in export_df.columns]
    st.download_button(
        "Export All Leads to CSV",
        data=export_df[export_cols].to_csv(index=False).encode("utf-8-sig"),
        file_name="egast_saved_leads.csv", mime="text/csv",
        key="export_saved_leads_csv",
    )

    st.divider()
    st.subheader("Manage a Lead")
    st.caption("Choose a company to update its assignment, save notes, or delete it.")
    if filtered.empty:
        st.info("No leads match your search or filters.")
        return

    options = {
        f"{row.get('company_name') or 'Unknown Company'} · ID {int(row['id'])}": int(row["id"])
        for _, row in filtered.iterrows()
    }
    selected_label = st.selectbox("Select Company", list(options.keys()), key="saved_lead_choice")
    lead_id = options[selected_label]
    row = df.loc[df["id"] == lead_id].iloc[0]
    company = str(row.get("company_name") or "Unknown Company")
    website = str(row.get("website") or "").strip()
    email = str(row.get("email") or "").strip()
    current_employee = str(row.get("employee_name") or "Unassigned").strip()
    if current_employee not in EMPLOYEES:
        current_employee = "Unassigned"

    with st.container(border=True):
        st.subheader(company)
        st.caption(f"Lead ID: {lead_id}")
        left, right = st.columns(2)
        with left:
            st.write(f"**Country:** {row.get('country') or '—'}")
            st.write(f"**Industry:** {row.get('industry') or '—'}")
            st.write(f"**Buyer Status:** {row.get('buyer_status') or '—'}")
        with right:
            st.write(f"**Assigned To:** {current_employee}")
            if website:
                st.markdown(f"[Open Website]({website})")
            if email:
                st.markdown(f"[Send Email](mailto:{email})")

        st.divider()
        st.markdown("**Employee Assignment**")
        employee_key = f"employee_{lead_id}"
        assignment_options = ["Unassigned"] + EMPLOYEES
        # Initialize the widget from the database; after save, rerun reads DB again.
        if employee_key not in st.session_state:
            st.session_state[employee_key] = current_employee
        elif st.session_state[employee_key] not in assignment_options:
            st.session_state[employee_key] = current_employee
        selected_employee = st.selectbox("Assign Employee", assignment_options, key=employee_key)
        assign_col, remove_col = st.columns(2)
        with assign_col:
            if st.button("Save Assignment", key=f"assign_{lead_id}", type="primary", use_container_width=True):
                try:
                    if selected_employee == "Unassigned":
                        remove_assignment(lead_id)
                    else:
                        assign_lead(lead_id, selected_employee)
                    st.session_state.pop(employee_key, None)
                    st.session_state["saved_leads_message"] = f"{company} assigned to {selected_employee}."
                    st.rerun()
                except Exception as error:
                    st.session_state["saved_leads_error"] = f"Assignment failed: {type(error).__name__}: {error}"
                    st.rerun()
        with remove_col:
            if st.button("Remove Assignment", key=f"remove_assignment_{lead_id}", use_container_width=True):
                try:
                    remove_assignment(lead_id)
                    st.session_state.pop(employee_key, None)
                    st.session_state["saved_leads_message"] = f"Assignment removed for {company}."
                    st.rerun()
                except Exception as error:
                    st.session_state["saved_leads_error"] = f"Could not remove assignment: {error}"
                    st.rerun()

        st.divider()
        st.markdown("**Personal Notes**")
        note_key = f"personal_note_{lead_id}"
        if note_key not in st.session_state:
            st.session_state[note_key] = notes_by_id.get(lead_id, "")
        st.text_area("Notes", key=note_key, placeholder="Contact person, follow-up date, discussion notes...", height=100)
        if st.button("Save Notes", key=f"save_note_{lead_id}", use_container_width=True):
            try:
                save_lead_note(lead_id, st.session_state[note_key])
                st.session_state["saved_leads_message"] = f"Notes saved for {company}."
                st.rerun()
            except Exception as error:
                st.session_state["saved_leads_error"] = f"Could not save notes: {type(error).__name__}: {error}"
                st.rerun()

        st.divider()
        st.markdown("**Delete Lead**")
        confirm_key = "confirm_delete_lead_id"
        if st.session_state.get(confirm_key) != lead_id:
            if st.button("Delete Lead", key=f"delete_{lead_id}", use_container_width=True):
                st.session_state[confirm_key] = lead_id
                st.rerun()
        else:
            st.warning(f"Delete {company} permanently, including its notes and assignment?")
            delete_col, cancel_col = st.columns(2)
            with delete_col:
                if st.button("Confirm Delete", key=f"confirm_delete_{lead_id}", type="primary", use_container_width=True):
                    try:
                        delete_lead(lead_id)
                        st.session_state.pop(note_key, None)
                        st.session_state.pop(employee_key, None)
                        st.session_state.pop(confirm_key, None)
                        st.session_state.pop("saved_lead_choice", None)
                        st.session_state["saved_leads_message"] = f"{company} was deleted successfully."
                        st.rerun()
                    except Exception as error:
                        st.session_state["saved_leads_error"] = f"Delete failed: {type(error).__name__}: {error}"
                        st.rerun()
            with cancel_col:
                if st.button("Cancel Delete", key=f"cancel_delete_{lead_id}", use_container_width=True):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()


# =========================================================
# MAIN APPLICATION
# =========================================================

def main():
    st.set_page_config(
        page_title="EGAST AI Sales Agent",
        page_icon="🍊",
        layout="wide",
    )

    initialize_database()
    initialize_assignments()

    st.title("🍊 EGAST AI Sales Agent")

    st.caption(
        "Discover potential buyers, qualify companies with AI, "
        "and coordinate employee lead assignments."
    )

    discover_tab, employees_tab, saved_tab = st.tabs(
        [
            "🔎 Discover Buyers",
            "👥 Employees & Assignments",
            "📋 Saved Leads",
        ]
    )

    with discover_tab:
        show_discover_buyers()

    with employees_tab:
        show_employee_assignments()

    with saved_tab:
        show_saved_leads()


if __name__ == "__main__":
    main()