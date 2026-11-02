import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

source = Path("data/leads_for_review.csv")
output = Path("data/training/training_error_analysis.csv")

df = pd.read_csv(source)
features = [
    "company_name", "country", "industry", "website",
    "email", "products", "discovered_links"
]
valid = {"potential_buyer", "not_buyer", "uncertain"}
df["human_label"] = df["human_label"].fillna("").str.strip().str.lower()
df = df[df["human_label"].isin(valid)].copy()

def make_text(row):
    return " | ".join(
        f"{c}: {row[c]}" for c in features
        if pd.notna(row[c]) and str(row[c]).strip()
    )

df["training_text"] = df.apply(make_text, axis=1)
df = df[df["training_text"].str.len() > 0].copy()

model = Pipeline([
    ("features", FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ("char", TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True
        )),
    ])),
    ("classifier", LogisticRegression(
        max_iter=2000, class_weight="balanced", random_state=42
    )),
])

counts = df["human_label"].value_counts()
cv = StratifiedKFold(
    n_splits=min(4, int(counts.min())), shuffle=True, random_state=42
)
predictions = cross_val_predict(model, df["training_text"], df["human_label"], cv=cv)

df["cv_prediction"] = predictions
df["correct"] = df["human_label"] == df["cv_prediction"]

columns = [
    c for c in [
        "id", "company_name", "country", "industry", "website",
        "products", "human_label", "cv_prediction", "correct", "review_notes"
    ] if c in df.columns
]
output.parent.mkdir(parents=True, exist_ok=True)
df[columns].sort_values(["correct", "human_label"]).to_csv(output, index=False)

print("Saved:", output)
print("\nErrors by true label:")
print(df.loc[~df["correct"], "human_label"].value_counts().to_string())
print("\nMisclassified leads:")
print(df.loc[~df["correct"], columns].to_string(index=False))
