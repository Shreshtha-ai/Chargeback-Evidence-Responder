import csv
import random
import uuid #used to generate UNIVERSALLY UNIQUE IDENTIFIERS(128 BIT NUMBERS)
from datetime import datetime, timedelta #used to generate random date/time values

from faker import Faker #generates pseudo-random data

fake = Faker("en_IN")  # Indian locale -> realistic names/addresses for an Indian fintech context
random.seed(42)         # fixed seed for reproducibility

N_CUSTOMERS = 250
N_ORDERS = 500
DISPUTE_RATE = 0.22

CATEGORIES = ["Electronics", "Fashion", "Home & Kitchen", "Beauty", "Food", "Books", "Sports"] #product category
DISPUTE_REASONS = ["items_not_received", "unauthorized_transaction", "not_as_described", "duplicate_charge"]

def random_date(start_days_ago =180, end_days_ago =1): #used to generate random  transaction/order timestamps 
    delta_days = random.randint(end_days_ago, start_days_ago)
    return datetime.now() - timedelta(days=delta_days, hours=random.randint(0, 23))

def generate_customers(n):
    customers = []
    for _ in range(n):
        account_age_days = random.randint(1, 1500)
        is_repeat_disputer = random.random() < 0.08 #8% of customers are repeat disputer 
        customers.append({
            "customer_id": f"CUST_{uuid.uuid4().hex[:8]}",
            "name": fake.name(),
            "account_age_days": account_age_days,
            "past_orders_count": random.randint(0, 40),
            "past_disputes_filed": random.randint(2, 6) if is_repeat_disputer else random.randint(0, 1),
            "is_repeat_disputer": is_repeat_disputer, 
        })
    return customers

def generate_customer_devices(customers):
    devices = []
    for c in customers:
        n_devices = random.choices([1,2,3], weights=[0.55,0.35,0.10])[0]
        for _ in range(n_devices):
            devices.append({
                "customer_id": c["customer_id"],
                "device_id": f"DEV_{uuid.uuid4().hex[:10]}",
                "first_seen_date": random_date(start_days_ago=c["account_age_days"] if c["account_age_days"] > 0 else 1).isoformat(),
                "times_used": random.randint(1, 25),
            })
    return devices


def generate_orders(customers, customer_devices_by_cust, n):
    orders = []
    for _ in range(n):
        cust = random.choice(customers)
        known_devices = customer_devices_by_cust.get(cust["customer_id"], [])
        use_known_device = random.random() < 0.88
        if use_known_device and known_devices:
            device_id = random.choice(known_devices)["device_id"]
        else:
            device_id = f"DEV_{uuid.uuid4().hex[:10]}"  

        checkout_ip = fake.ipv4()
        orders.append({
            "order_id": f"ORD_{uuid.uuid4().hex[:8]}",
            "customer_id": cust["customer_id"],
            "order_timestamp": random_date().isoformat(),
            "amount_inr": round(random.uniform(299, 45000), 2),
            "item_category": random.choice(CATEGORIES),
            "checkout_ip": fake.ipv4(),
            "checkout_device_id": device_id,

        })
    return orders

def generate_deliveries(orders):
    deliveries = []
    for o in orders:
        status = random.choices(
            ["delivered", "lost_in_transit", "delayed", "returned_to_sender"],
            weights=[0.80, 0.07, 0.08, 0.05],
        )[0]
        signature_captured = status == "delivered" and random.random() < 0.7
        deliveries.append({
            "order_id": o["order_id"],
            "delivery_status": status,
            "delivery_timestamp": (
                (datetime.fromisoformat(o["order_timestamp"]) + timedelta(days=random.randint(1, 7))).isoformat()
                if status in ("delivered", "returned_to_sender") else ""
            ),
            "signature_captured": signature_captured,
            "delivery_photo_available": signature_captured and random.random() < 0.6,
        })
    return deliveries

def assign_dispute_labels(order, delivery, customer, is_known_device):

    score_fraud = 0
    score_friendly =0
    score_merchant_error =0

    is_established_account = customer["past_orders_count"] >= 3 and customer["account_age_days"] >= 30

    if not is_known_device:
        if is_established_account:
            score_fraud += 2.5  # established customer + new device = genuinely unusual
        else:
            score_fraud += 0.3  # new customer + new device = expected, barely a signal
    if not delivery["signature_captured"]:
        score_fraud += 1
        score_merchant_error += 1
    if customer["is_repeat_disputer"]:
        score_friendly += 2.3
    if delivery["signature_captured"] or delivery["delivery_photo_available"]:
        score_friendly += 1.4
    if delivery["delivery_status"] in ("lost_in_transit", "delayed"):
        score_merchant_error += 3
    if customer["account_age_days"] < 20:
        score_fraud += 1.5

    #adding some random noise as data in not always perfect 
    score_fraud += random.uniform(0, 1.2)
    score_friendly += random.uniform(0, 1.2)
    score_merchant_error += random.uniform(0, 1.2)
 
    scores = {"fraud": score_fraud, "friendly_fraud": score_friendly, "merchant_error": score_merchant_error}
    return max(scores, key=scores.get)


CLAIM_TEXT_TEMPLATES = {"fraud": [
        "I have never made this purchase, please reverse the charge immediately.",
        "This transaction was not authorized by me or anyone on my account.",
    ],
    "friendly_fraud": [
        "I never received this item, please refund me.",
        "This does not match what I ordered, I want my money back.",
        "I don't recall making this purchase and would like a refund.",
    ],
    "merchant_error": [
        "My order shows delivered but I never got the package.",
        "Tracking has not updated in over a week, where is my order?",
    ],
}

def generate_disputes(orders, deliveries_by_order, customers_by_id, known_device_ids_by_cust):
    disputes = []
    n_disputes = int(len(orders) * DISPUTE_RATE)
    disputed_orders = random.sample(orders, n_disputes)

    for order in disputed_orders:
        delivery = deliveries_by_order[order["order_id"]]
        customer = customers_by_id[order["customer_id"]]
        known_devices = known_device_ids_by_cust.get(order["customer_id"], set())
        is_known_device = order["checkout_device_id"] in known_devices

        label = assign_dispute_labels(order,delivery,customer,is_known_device)

        reason = {
            "fraud": "unauthorized_transaction",
            "friendly_fraud": random.choice(["item_not_received", "not_as_described"]),
            "merchant_error": "item_not_received",
        }[label]

        disputes.append({
            "dispute_id": f"DSP_{uuid.uuid4().hex[:8]}",
            "order_id": order["order_id"],
            "dispute_date": (datetime.fromisoformat(order["order_timestamp"]) + timedelta(days=random.randint(3, 25))).isoformat(),
            "dispute_reason_code": reason,
            "customer_claim_text": random.choice(CLAIM_TEXT_TEMPLATES[label]),
            "label": label,
        })

    return disputes

def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    customers = generate_customers(N_CUSTOMERS)
 
    customer_devices = generate_customer_devices(customers)
    devices_by_cust = {}
    for d in customer_devices:
        devices_by_cust.setdefault(d["customer_id"], []).append(d)
    known_device_ids_by_cust = {cid: set(d["device_id"] for d in devs) for cid, devs in devices_by_cust.items()}
 
    orders = generate_orders(customers, devices_by_cust, N_ORDERS)
    deliveries = generate_deliveries(orders)
    deliveries_by_order = {d["order_id"]: d for d in deliveries}
    customers_by_id = {c["customer_id"]: c for c in customers}
 
    disputes = generate_disputes(orders, deliveries_by_order, customers_by_id, known_device_ids_by_cust)
 
    write_csv("../data/customers.csv", customers)
    write_csv("../data/customer_devices.csv", customer_devices)
    write_csv("../data/orders.csv", orders)
    write_csv("../data/deliveries.csv", deliveries)
    write_csv("../data/disputes.csv", disputes)
 
    label_counts = {}
    for d in disputes:
        label_counts[d["label"]] = label_counts.get(d["label"], 0) + 1
 
    n_new_device_orders = sum(
        1 for o in orders if o["checkout_device_id"] not in known_device_ids_by_cust.get(o["customer_id"], set())
    )
 
    print(f"Generated {len(customers)} customers, {len(customer_devices)} known devices, "
          f"{len(orders)} orders, {len(disputes)} disputes.")
    print(f"Orders on a brand-new (unseen) device: {n_new_device_orders} / {len(orders)}")
    print(f"Label distribution: {label_counts}")
 
 
if __name__ == "__main__":
    main()

            

            









    


    
        




        





