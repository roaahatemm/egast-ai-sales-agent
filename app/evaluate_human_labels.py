
from pathlib import Path
import sqlite3

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = ROOT / "data" / "leads_for_review.csv"
DATABASE_FILE = ROOT / "data" / "leads.db"
ERROR_FILE = ROOT / "data" / "qualification_errors.csv"

POSITIVE = "potential_buyer"
NEGATIVE = "not_buyer"
DEFINITIVE = {POSITIVE, NEGATIVE}


def normalize_label(value):
    if pd.isna(value):
        return None

    value = str(value).strip().lower()
    return value if value in {POSITIVE, NEGATIVE, "uncertain"} else None


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Cannot find {INPUT_FILE}")

    if not DATABASE_FILE.exists():
        raise FileNotFoundError(f"Cannot find {DATABASE_FILE}")

    # Human labels remain in the review CSV.
    human_df = pd.read_csv(INPUT_FILE)

    required = {"id", "company_name", "human_label"}
    missing = required - set(human_df.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {sorted(missing)}")

    # Fetch the latest AI predictions from SQLite.
    with sqlite3.connect(DATABASE_FILE) as connection:
        ai_df = pd.read_sql_query(
            """
            SELECT
                id,
                buyer_status AS ai_prediction,
                ai_confidence,
                ai_evidence,
                qualification_reason,
                ai_qualification_error
            FROM leads
            """,
            connection,
        )

    # IDs are the matching key; never match by company name.
    human_df["id"] = pd.to_numeric(human_df["id"], errors="coerce")
    ai_df["id"] = pd.to_numeric(ai_df["id"], errors="coerce")

    if human_df["id"].isna().any():
        raise ValueError("Some CSV rows have missing or invalid lead IDs.")

    if human_df["id"].duplicated().any():
        raise ValueError("The review CSV contains duplicate lead IDs.")

    df = human_df.merge(
        ai_df,
        on="id",
        how="left",
        validate="one_to_one",
    )

    df["human_label_clean"] = df["human_label"].apply(normalize_label)
    df["ai_prediction"] = df["ai_prediction"].apply(normalize_label)

    reviewed = df[df["human_label_clean"].isin(DEFINITIVE)].copy()
    evaluated = reviewed[
        reviewed["ai_prediction"].isin(DEFINITIVE)
    ].copy()

    print("\n=== EGAST AI QUALIFICATION EVALUATION ===")
    print(f"Human-reviewed CSV rows: {len(df)}")
    print(f"Definitive human labels: {len(reviewed)}")
    print(f"Human-uncertain or missing labels: {len(df) - len(reviewed)}")
    print(f"Current definitive AI predictions: {len(evaluated)}")

    if len(reviewed):
        print(
            "AI prediction coverage: "
            f"{len(evaluated) / len(reviewed):.1%}"
        )
    else:
        print("AI prediction coverage: N/A")

    print("\n=== CURRENT AI PREDICTION COUNTS (REVIEWED LEADS) ===")
    print(
        df["ai_prediction"]
        .value_counts(dropna=False)
        .to_string()
    )

    if evaluated.empty:
        print("\nNo rows have both definitive human labels "
              "and definitive AI predictions.")
        return

    actual = evaluated["human_label_clean"]
    predicted = evaluated["ai_prediction"]

    tp = int(((actual == POSITIVE) & (predicted == POSITIVE)).sum())
    fp = int(((actual == NEGATIVE) & (predicted == POSITIVE)).sum())
    fn = int(((actual == POSITIVE) & (predicted == NEGATIVE)).sum())
    tn = int(((actual == NEGATIVE) & (predicted == NEGATIVE)).sum())

    accuracy = (tp + tn) / len(evaluated)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )

    print("\n=== CONFUSION MATRIX ===")
    print("Rows = human labels; columns = AI predictions")
    print(f"{'':20} {'AI buyer':>12} {'AI not buyer':>15}")
    print(f"{'Human buyer':20} {tp:12} {fn:15}")
    print(f"{'Human not buyer':20} {fp:12} {tn:15}")

    print("\n=== METRICS ===")
    print(f"Accuracy:  {accuracy:.1%}")
    print(f"Precision: {precision:.1%}")
    print(f"Recall:    {recall:.1%}")
    print(f"F1 score:  {f1:.1%}")

    evaluated["evaluation_result"] = evaluated.apply(
        lambda row: (
            "false_positive"
            if row["human_label_clean"] == NEGATIVE
            and row["ai_prediction"] == POSITIVE
            else "false_negative"
            if row["human_label_clean"] == POSITIVE
            and row["ai_prediction"] == NEGATIVE
            else "correct"
        ),
        axis=1,
    )

    errors = evaluated[
        evaluated["evaluation_result"] != "correct"
    ].copy()

    columns_to_show = [
        col for col in [
            "id",
            "company_name",
            "website",
            "ai_prediction",
            "human_label",
            "ai_confidence",
            "ai_evidence",
            "qualification_reason",
            "review_notes",
            "evaluation_result",
        ]
        if col in errors.columns
    ]

    print("\n=== CLASSIFICATION ERRORS ===")
    if errors.empty:
        print("No classification errors among evaluated rows.")
    else:
        print(errors[columns_to_show].to_string(index=False))

    # Also report predictions that need review instead of hiding them.
    needs_review = reviewed[
        ~reviewed["ai_prediction"].isin(DEFINITIVE)
    ].copy()

    print("\n=== UNRESOLVED PREDICTIONS ===")
    print(f"Definitively human-labeled leads needing AI review: {len(needs_review)}")

    if not needs_review.empty:
        review_columns = [
            col for col in [
                "id", "company_name", "website",
                "ai_prediction", "ai_qualification_error",
                "human_label", "review_notes",
            ]
            if col in needs_review.columns
        ]
        print(needs_review[review_columns].to_string(index=False))

    errors[columns_to_show].to_csv(ERROR_FILE, index=False)
    print(f"\nError report saved to: {ERROR_FILE}")
    print("Database and human labels were not modified.")


if __name__ == "__main__":
    main()

