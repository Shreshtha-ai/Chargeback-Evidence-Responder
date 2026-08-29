

import os
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

# Resolved relative to THIS FILE's location, not the caller's cwd -- same
# reasoning as tools.py: this module gets imported from src/ (via agent.py)
# AND from eval/run_eval.py, which live in different directories.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_THIS_DIR, "..", "data")
MODEL_PATH = os.path.join(_THIS_DIR, "classifier_model.joblib")


def build_feature_table():
    
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

    joblib.dump(model, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")
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
    
    model = joblib.load(MODEL_PATH)
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