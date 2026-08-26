"""
classifier.py

A lightweight structured-feature classifier that predicts a probability
distribution over {fraud, friendly_fraud, merchant_error} for a dispute.

IMPORTANT: this is deliberately ONE TOOL the agent can call, not the
system's final answer. The agent still has to gather evidence, reason
about it, and justify a decision -- the classifier just gives it a
quick, structured prior to reason with (the same way a real fraud
analyst might glance at a risk score before reading the case details,
not accept the score blindly as the verdict).

Features used (all derived from tools.py, no ground-truth leakage):
    - is_known_device        (from check_device_familiarity)
    - is_established_account (derived: past_orders_count >= 3 and account_age_days >= 30)
    - account_age_days
    - past_orders_count
    - past_disputes_filed
    - signature_captured
    - delivery_photo_available
    - delivery_status_bad     (lost_in_transit or delayed)
    - amount_inr

Deliberately excluded: is_repeat_disputer, dispute label -- ground truth,
never a feature.

Train/test split is fixed (seed=42, 80/20) so results are reproducible --
this is the number you'll report in eval/eval_results.json later.
"""

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

DATA_DIR = "../data"


def build_feature_table():
    """
    Joins the raw CSVs into one feature table, one row per dispute.
    This mirrors exactly what the agent's tools would return if called
    for that dispute -- kept as a single function so it's obvious the
    classifier sees nothing the agent's tools couldn't also retrieve.
    """
    customers = pd.read_csv(f"{DATA_DIR}/customers.csv")
    devices = pd.read_csv(f"{DATA_DIR}/customer_devices.csv")
    orders = pd.read_csv(f"{DATA_DIR}/orders.csv")
    deliveries = pd.read_csv(f"{DATA_DIR}/deliveries.csv")
    disputes = pd.read_csv(f"{DATA_DIR}/disputes.csv")

    known_device_pairs = set(zip(devices["customer_id"], devices["device_id"]))

    rows = []
    for _, d in disputes.iterrows():
        order = orders[orders["order_id"] == d["order_id"]].iloc[0]
        delivery = deliveries[deliveries["order_id"] == d["order_id"]].iloc[0]
        customer = customers[customers["customer_id"] == order["customer_id"]].iloc[0]

        is_known_device = (order["customer_id"], order["checkout_device_id"]) in known_device_pairs
        is_established = customer["past_orders_count"] >= 3 and customer["account_age_days"] >= 30

        rows.append({
            "dispute_id": d["dispute_id"],
            "is_known_device": int(is_known_device),
            "is_established_account": int(is_established),
            "account_age_days": customer["account_age_days"],
            "past_orders_count": customer["past_orders_count"],
            "past_disputes_filed": customer["past_disputes_filed"],
            "signature_captured": int(delivery["signature_captured"]),
            "delivery_photo_available": int(delivery["delivery_photo_available"]),
            "delivery_status_bad": int(delivery["delivery_status"] in ("lost_in_transit", "delayed")),
            "amount_inr": order["amount_inr"],
            "label": d["label"],
        })
    return pd.DataFrame(rows)


FEATURE_COLS = [
    "is_known_device", "is_established_account", "account_age_days",
    "past_orders_count", "past_disputes_filed", "signature_captured",
    "delivery_photo_available", "delivery_status_bad", "amount_inr",
]


def train_and_evaluate():
    df = build_feature_table()
    X = df[FEATURE_COLS]
    y = df["label"]

    # Fixed seed split -- same test set every run, so metrics are comparable
    # across code changes and honest (not cherry-picked).
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = GradientBoostingClassifier(random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print("=== Classifier eval on held-out test set ===")
    print(classification_report(y_test, preds, zero_division=0))

    joblib.dump(model, "classifier_model.joblib")
    print("Model saved to classifier_model.joblib")
    return model


def predict_fraud_likelihood(
    is_known_device: int,
    is_established_account: int,
    account_age_days: int,
    past_orders_count: int,
    past_disputes_filed: int,
    signature_captured: int,
    delivery_photo_available: int,
    delivery_status_bad: int,
    amount_inr: float,
) -> dict:
    """
    Tool function: takes the 9 feature values as separate keyword
    arguments (matching the FUNCTION_DECLARATIONS schema in agent.py,
    which lists each as its own parameter) and returns class
    probabilities. This is what the agent calls -- it does NOT read CSVs
    or know about dispute_ids, it just scores whatever features it's given.
    """
    model = joblib.load("classifier_model.joblib")
    features = {
        "is_known_device": is_known_device,
        "is_established_account": is_established_account,
        "account_age_days": account_age_days,
        "past_orders_count": past_orders_count,
        "past_disputes_filed": past_disputes_filed,
        "signature_captured": signature_captured,
        "delivery_photo_available": delivery_photo_available,
        "delivery_status_bad": delivery_status_bad,
        "amount_inr": amount_inr,
    }
    X = pd.DataFrame([features])[FEATURE_COLS]
    proba = model.predict_proba(X)[0]
    classes = model.classes_
    return {cls: round(float(p), 3) for cls, p in zip(classes, proba)}


if __name__ == "__main__":
    train_and_evaluate()