

import os
import pandas as pd

# ---------------------------------------------------------------------------
# Load once at import time. Paths are resolved relative to THIS FILE's
# location (not the current working directory) so tools.py works correctly
# whether it's run from src/, imported from eval/run_eval.py, or anywhere
# else -- cwd-relative paths like "../data/x.csv" would silently break the
# moment this module is imported from a different working directory.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_THIS_DIR, "..", "data")

_customers = pd.read_csv(os.path.join(_DATA_DIR, "customers.csv"))
_customer_devices = pd.read_csv(os.path.join(_DATA_DIR, "customer_devices.csv"))
_orders = pd.read_csv(os.path.join(_DATA_DIR, "orders.csv"))
_deliveries = pd.read_csv(os.path.join(_DATA_DIR, "deliveries.csv"))
_disputes = pd.read_csv(os.path.join(_DATA_DIR, "disputes.csv"))


def get_dispute_details(dispute_id: str) -> dict:
    
    row = _disputes[_disputes["dispute_id"] == dispute_id]
    if row.empty:
        return {"error": f"No dispute found with id {dispute_id}"}
    r = row.iloc[0]
    return {
        "dispute_id": r["dispute_id"],
        "order_id": r["order_id"],
        "dispute_date": r["dispute_date"],
        "dispute_reason_code": r["dispute_reason_code"],
        "customer_claim_text": r["customer_claim_text"],
        # NOTE: r["label"] deliberately excluded -- ground truth, not agent input
    }


def get_order_details(order_id: str) -> dict:
    """
    Tool: look up what was actually ordered -- amount, category, and the
    checkout fingerprint (device/IP) used at time of purchase.
    """
    row = _orders[_orders["order_id"] == order_id]
    if row.empty:
        return {"error": f"No order found with id {order_id}"}
    r = row.iloc[0]
    return {
        "order_id": r["order_id"],
        "customer_id": r["customer_id"],
        "order_timestamp": r["order_timestamp"],
        "amount_inr": float(r["amount_inr"]),
        "item_category": r["item_category"],
        "checkout_ip": r["checkout_ip"],
        "checkout_device_id": r["checkout_device_id"],
    }


def get_delivery_proof(order_id: str) -> dict:
    """
    Tool: look up physical delivery evidence for an order.
    Purely physical facts -- status, signature, photo. No device/IP here,
    since a physical delivery has none (see our earlier discussion on why
    that field was removed from the schema).
    """
    row = _deliveries[_deliveries["order_id"] == order_id]
    if row.empty:
        return {"error": f"No delivery record found for order {order_id}"}
    r = row.iloc[0]
    return {
        "order_id": r["order_id"],
        "delivery_status": r["delivery_status"],
        "delivery_timestamp": r["delivery_timestamp"] if pd.notna(r["delivery_timestamp"]) else None,
        "signature_captured": bool(r["signature_captured"]),
        "delivery_photo_available": bool(r["delivery_photo_available"]),
    }


def get_customer_history(customer_id: str) -> dict:
    
    row = _customers[_customers["customer_id"] == customer_id]
    if row.empty:
        return {"error": f"No customer found with id {customer_id}"}
    r = row.iloc[0]
    return {
        "customer_id": r["customer_id"],
        "account_age_days": int(r["account_age_days"]),
        "past_orders_count": int(r["past_orders_count"]),
        "past_disputes_filed": int(r["past_disputes_filed"]),
    }


def check_device_familiarity(customer_id: str, device_id: str) -> dict:
    """
    Tool: check whether a given device has been seen before for this
    customer, and if so, how established that device is.

    This directly implements the fraud signal we discussed: an unknown
    device is only meaningfully suspicious when paired with an
    ESTABLISHED account -- a brand-new customer's first order is
    trivially on an "unknown" device, so the agent's prompt (built next)
    needs to reason about that nuance itself using the account history
    from get_customer_history(), rather than this tool making that
    judgment call for it. This tool just reports the raw fact.
    """
    matches = _customer_devices[
        (_customer_devices["customer_id"] == customer_id) & (_customer_devices["device_id"] == device_id)
    ]
    if matches.empty:
        return {
            "customer_id": customer_id,
            "device_id": device_id,
            "is_known_device": False,
            "times_used": 0,
            "first_seen_date": None,
        }
    r = matches.iloc[0]
    return {
        "customer_id": customer_id,
        "device_id": device_id,
        "is_known_device": True,
        "times_used": int(r["times_used"]),
        "first_seen_date": r["first_seen_date"],
    }


# ---------------------------------------------------------------------------
# Quick manual test -- run this file directly to sanity-check the tools
# against a real dispute from your dataset before wiring up the agent.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_dispute_id = _disputes.iloc[0]["dispute_id"]
    print(f"Testing tools against dispute: {sample_dispute_id}\n")

    dispute = get_dispute_details(sample_dispute_id)
    print("1. get_dispute_details ->", dispute)

    order = get_order_details(dispute["order_id"])
    print("2. get_order_details ->", order)

    delivery = get_delivery_proof(dispute["order_id"])
    print("3. get_delivery_proof ->", delivery)

    customer = get_customer_history(order["customer_id"])
    print("4. get_customer_history ->", customer)

    device_check = check_device_familiarity(order["customer_id"], order["checkout_device_id"])
    print("5. check_device_familiarity ->", device_check)

    # Reveal the ground-truth label ONLY here, for your own manual sanity check
    # -- never expose this path in the actual agent.
    true_label = _disputes[_disputes["dispute_id"] == sample_dispute_id].iloc[0]["label"]
    print(f"\n(For your eyes only) Ground truth label: {true_label}")

