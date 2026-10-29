

import sqlite3
import json
from pathlib import Path
from urllib.parse import urlparse

DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "leads.db"

GENERIC_NAMES = {
    "",
    "unknown",
    "home",
    "wholesale",
    "importer",
    "fruit importer",
    "dutch fruit & vegetable importer",
}

AI_COLUMNS = {
    "is_company": "INTEGER",
    "buyer_status": "TEXT",
    "buyer_type": "TEXT",
    "products_of_interest": "TEXT",
    "target_country": "TEXT",
    "ai_evidence": "TEXT",
    "qualification_reason": "TEXT",
    "ai_confidence": "INTEGER",
    "recommended_next_action": "TEXT",
    "ai_qualification_error": "TEXT",
}


def normalize_website(website: str | None) -> str:
    """Normalize a website so URL variations can be matched."""
    if not website:
        return ""

    value = website.strip().lower()
    if not value:
        return ""

    if "://" not in value:
        value = "https://" + value

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()

    if host.startswith("www."):
        host = host[4:]

    return host


def name_quality(name: str | None) -> int:
    """Prefer meaningful company names over generic page titles."""
    cleaned = (name or "").strip().lower()

    if not cleaned or cleaned in GENERIC_NAMES:
        return 0

    return 1


def merge_text(existing: str | None, incoming: str | None) -> str:
    """Keep existing information when new data is blank."""
    old = (existing or "").strip()
    new = (incoming or "").strip()
    return new or old


def merge_lists(existing: str | None, incoming) -> str:
    """Merge comma-separated values without duplicates."""
    old_items = (existing or "").split(",")

    if isinstance(incoming, list):
        new_items = incoming
    elif incoming:
        new_items = str(incoming).split(",")
    else:
        new_items = []

    merged = []
    seen = set()

    for item in old_items + new_items:
        item = str(item).strip()
        key = item.casefold()

        if item and key not in seen:
            seen.add(key)
            merged.append(item)

    return ", ".join(merged)


def initialize_database() -> None:
    """Create the leads table and safely add missing AI columns."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                country TEXT,
                industry TEXT,
                website TEXT,
                email TEXT,
                score REAL NOT NULL DEFAULT 0,
                products TEXT,
                discovered_links TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_name, website)
            )
        """)

        existing_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(leads)"
            ).fetchall()
        }

        for column_name, column_type in AI_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE leads ADD COLUMN "
                    f"{column_name} {column_type}"
                )


def save_lead(lead: dict) -> int:
    """
    Save a lead or update an existing company with the same website.

    Preserves existing duplicate detection and merging logic.
    Returns the existing or newly created database ID.
    """
    initialize_database()

    company_name = (lead.get("company_name") or "Unknown").strip()
    website = (lead.get("website") or "").strip()
    normalized_site = normalize_website(website)

    incoming_score = float(lead.get("score") or 0)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        candidates = []

        if normalized_site:
            rows = connection.execute("""
                SELECT * FROM leads
                WHERE website IS NOT NULL AND website != ''
            """).fetchall()

            candidates = [
                row for row in rows
                if normalize_website(row["website"]) == normalized_site
            ]

        existing = None

        if candidates:
            existing = max(
                candidates,
                key=lambda row: (
                    name_quality(row["company_name"]),
                    float(row["score"] or 0),
                    len(row["company_name"] or ""),
                ),
            )

        products = merge_lists(
            existing["products"] if existing else "",
            lead.get("products", []),
        )

        links = merge_lists(
            existing["discovered_links"] if existing else "",
            lead.get("discovered_links", []),
        )

        if existing:
            old_name = existing["company_name"] or ""

            if name_quality(company_name) > name_quality(old_name):
                final_name = company_name
            else:
                final_name = old_name or company_name

            final_website = existing["website"] or website
            final_country = merge_text(
                existing["country"], lead.get("country")
            )
            final_industry = merge_text(
                existing["industry"], lead.get("industry")
            )
            final_email = merge_text(
                existing["email"], lead.get("email")
            )
            final_score = max(
                float(existing["score"] or 0), incoming_score
            )

            connection.execute("""
                UPDATE leads
                SET company_name = ?,
                    country = ?,
                    industry = ?,
                    website = ?,
                    email = ?,
                    score = ?,
                    products = ?,
                    discovered_links = ?
                WHERE id = ?
            """, (
                final_name,
                final_country,
                final_industry,
                final_website,
                final_email,
                final_score,
                products,
                links,
                existing["id"],
            ))

            return existing["id"]

        connection.execute("""
            INSERT INTO leads (
                company_name, country, industry, website,
                email, score, products, discovered_links
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_name, website) DO UPDATE SET
                country = COALESCE(
                    NULLIF(excluded.country, ''), leads.country
                ),
                industry = COALESCE(
                    NULLIF(excluded.industry, ''), leads.industry
                ),
                email = COALESCE(
                    NULLIF(excluded.email, ''), leads.email
                ),
                score = MAX(leads.score, excluded.score)
        """, (
            company_name,
            lead.get("country") or "",
            lead.get("industry") or "",
            website,
            lead.get("email") or "",
            incoming_score,
            products,
            links,
        ))

        row = connection.execute("""
            SELECT id FROM leads
            WHERE company_name = ? AND website = ?
        """, (company_name, website)).fetchone()

        return row["id"]


def save_ai_qualification(
    lead_id: int,
    qualification: dict | None = None,
    error: str | None = None,
) -> None:
    """Save AI qualification separately from the original lead fields."""
    initialize_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        if qualification is None:
            connection.execute("""
                UPDATE leads
                SET ai_qualification_error = ?
                WHERE id = ?
            """, (
                error or "AI qualification failed.",
                lead_id,
            ))
            return

        connection.execute("""
            UPDATE leads
            SET is_company = ?,
                buyer_status = ?,
                buyer_type = ?,
                products_of_interest = ?,
                target_country = ?,
                ai_evidence = ?,
                qualification_reason = ?,
                ai_confidence = ?,
                recommended_next_action = ?,
                ai_qualification_error = NULL
            WHERE id = ?
        """, (
            int(qualification["is_company"]),
            qualification["buyer_status"],
            qualification["buyer_type"],
            json.dumps(
                qualification["products_of_interest"],
                ensure_ascii=False,
            ),
            qualification["target_country"],
            json.dumps(
                qualification["evidence"],
                ensure_ascii=False,
            ),
            qualification["qualification_reason"],
            qualification["confidence"],
            qualification["recommended_next_action"],
            lead_id,
        ))

def initialize_outreach_history() -> None:
    """Create outreach tracking without modifying existing leads."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS outreach_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                gmail_message_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES leads(id),
                UNIQUE(lead_id, recipient)
            )
        """)


def has_been_contacted(lead_id: int, recipient: str) -> bool:
    """Return True if an outreach attempt was already recorded."""
    initialize_outreach_history()

    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute("""
            SELECT 1
            FROM outreach_history
            WHERE lead_id = ?
              AND LOWER(recipient) = LOWER(?)
            LIMIT 1
        """, (lead_id, recipient.strip())).fetchone()

    return row is not None


def record_outreach(
    lead_id: int,
    recipient: str,
    subject: str,
    status: str,
    gmail_message_id: str | None = None,
) -> None:
    """Record a sending result and prevent duplicate lead-recipient entries."""
    initialize_outreach_history()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            INSERT INTO outreach_history (
                lead_id, recipient, subject, status, gmail_message_id
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lead_id, recipient) DO UPDATE SET
                status = excluded.status,
                gmail_message_id = excluded.gmail_message_id
        """, (
            lead_id,
            recipient.strip(),
            subject,
            status,
            gmail_message_id,
        ))
def get_all_leads() -> list[dict]:
    """Retrieve all saved leads, ordered by score."""
    initialize_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute("""
            SELECT * FROM leads
            ORDER BY score DESC
        """).fetchall()

        return [dict(row) for row in rows]
