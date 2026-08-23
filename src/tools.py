# pulls up the order check delivery status

import pandas as pd


#in real system  replace it with db querries 
_customers = pd.read.csv("../data/customers.csv")
_orders = pd.read.csv("../data/orders.csv")
_disputes = pd.read.csv("../data/disputes.csv")
_devices = pd.read.csv("../data/devices.csv")
_deliveries = pd.read.csv("../data/deliveries.csv")

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
    
    }

def get_order_details(order_id: str) -> dict:
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
    row = _deliveries[_deliveries["order_id"] == order_id]
    if row.empty:
        return {"error": f"No delivery proof found for order id {order_id}"}
    r = row.iloc[0]
    return {
        "order_id": r["order_id"],
        "delivery_status": r["delivery_status"],
        "delivery_timestamp": r["delivery_timestamp"] if pd.notna(r["delivery_timestamp"]) else None,
        "signature_captured": bool(r["signature_captured"]),
        "delivery_photo_available": bool(r["delivery_photo_available"]),
    }

