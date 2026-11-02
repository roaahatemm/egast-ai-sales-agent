from pathlib import Path
import json

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import classification_report, confusion_matrix

DATA = Path("data/training/leads_for_training_v2.csv")
OUT = Path("data/training")
MODEL_PATH = OUT / "lead_classifier_v2.joblib"
REPORT_PATH = OUT / "lead_classifier_v2_metrics.json"
PREDICTIONS_PATH = OUT / "lead_classifier_v2_cv_predictions.csv"

FEATURES = [
    "company_name", "country", "industry", "website",
    "email", "products", "discovered_links"
]
BUYER = "potential_buyer"
NOT_BUYER = "not_buyer"
UNCERTAIN = "uncertain"
THRESHOLD = 0.65


def build_text(row):
    parts = []
    for col in FEATURES:
        value = row.get(col)
        if pd.notna(value) and str(value).strip():
            parts.append(f"{col}: {str(value).strip()}")
    return " | ".join(parts)


def make_model():
    return Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(
                ngram_range=(1, 2),
                sublinear_tf=True,
                max_features=10000,
            )),
            ("character", TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                sublinear_tf=True,
                max_features=10000,
            )),
        ])),
        ("classifier", LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=42,
        )),
    ])


def classify_probability(p_buyer):
    # Require strong probability for either definitive decision.
    if p_buyer >= THRESHOLD:
        return BUYER
    if p_buyer <= 1 - THRESHOLD:
        return NOT_BUYER
    return UNCERTAIN


def main():
    df = pd.read_csv(DATA)
    required = {"training_label", *FEATURES}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df["training_label"] = (
        df["training_label"].fillna("").str.strip().str.lower()
    )
    df["training_text"] = df.apply(build_text, axis=1)
    df = df[df["training_text"].str.len() > 0].copy()

    definitive = df[df["training_label"].isin([BUYER, NOT_BUYER])].copy()
    uncertain_rows = df[df["training_label"] == UNCERTAIN].copy()

    counts = definitive["training_label"].value_counts()
    if set(counts.index) != {BUYER, NOT_BUYER} or counts.min() < 2:
        raise ValueError("Need at least two examples of both definitive classes.")

    X = definitive["training_text"]
    y = definitive["training_label"]
    folds = min(4, int(counts.min()))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)

    print("\n=== DATA ===")
    print(f"All labeled rows: {len(df)}")
    print(f"Definitive rows used for fitting: {len(definitive)}")
    print(f"Uncertain rows held out from fitting: {len(uncertain_rows)}")
    print(df["training_label"].value_counts().to_string())

    # Cross-validated probabilities: each definitive row is predicted
    # by a model that did not train on that row.
    evaluation_model = make_model()
    probabilities = cross_val_predict(
        evaluation_model, X, y, cv=cv, method="predict_proba"
    )
    classes = list(evaluation_model.fit(X, y).named_steps["classifier"].classes_)
    buyer_index = classes.index(BUYER)
    p_buyer = probabilities[:, buyer_index]
    cv_predictions = [classify_probability(p) for p in p_buyer]

    print(f"\n=== {folds}-FOLD CROSS-VALIDATION ===")
    print(f"Decision threshold: {THRESHOLD:.2f}")
    print(classification_report(
        y,
        cv_predictions,
        labels=[BUYER, NOT_BUYER, UNCERTAIN],
        zero_division=0,
    ))
    print("Confusion matrix (rows=true, columns=predicted):")
    print(confusion_matrix(
        y,
        cv_predictions,
        labels=[BUYER, NOT_BUYER, UNCERTAIN],
    ))
    coverage = sum(p != UNCERTAIN for p in cv_predictions) / len(y)
    print(f"Definitive-decision coverage: {coverage:.1%}")

    cv_results = definitive[
        [c for c in ["id", "company_name", "website", "training_label"] if c in definitive.columns]
    ].copy()
    cv_results["cv_buyer_probability"] = p_buyer
    cv_results["cv_prediction"] = cv_predictions
    cv_results["correct"] = cv_results["training_label"] == cv_results["cv_prediction"]
    OUT.mkdir(parents=True, exist_ok=True)
    cv_results.to_csv(PREDICTIONS_PATH, index=False)

    # Final fit uses all definitive human labels.
    final_model = make_model()
    final_model.fit(X, y)
    artifact = {
        "model": final_model,
        "threshold": THRESHOLD,
        "features": FEATURES,
        "classes": list(final_model.named_steps["classifier"].classes_),
        "training_rows": int(len(definitive)),
        "excluded_uncertain_rows": int(len(uncertain_rows)),
        "target": "training_label",
    }
    joblib.dump(artifact, MODEL_PATH)

    report = {
        "training_rows": int(len(definitive)),
        "held_out_uncertain_rows": int(len(uncertain_rows)),
        "class_counts": {str(k): int(v) for k, v in counts.items()},
        "cross_validation_folds": folds,
        "threshold": THRESHOLD,
        "definitive_decision_coverage": coverage,
        "classification_report": classification_report(
            y, cv_predictions,
            labels=[BUYER, NOT_BUYER, UNCERTAIN],
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix_labels": [BUYER, NOT_BUYER, UNCERTAIN],
        "confusion_matrix": confusion_matrix(
            y, cv_predictions,
            labels=[BUYER, NOT_BUYER, UNCERTAIN],
        ).tolist(),
        "warning": (
            "Small dataset. Probabilities are not guaranteed calibrated. "
            "Review predictions before operational use."
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== SECOND TRAINING RUN COMPLETE ===")
    print(f"Model:       {MODEL_PATH}")
    print(f"Metrics:     {REPORT_PATH}")
    print(f"CV results:  {PREDICTIONS_PATH}")
    print("Production database unchanged.")


if __name__ == "__main__":
    main()
