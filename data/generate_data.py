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

def generate_deliveries(orders, fraud_order_ids):
    deliveries = []
    for order in orders:
        is_fraud = order["order_id"] in fraud_order_ids
        if is_fraud:
            status = random.choices(
                ["delivered", "intercepted", "returned_to_sender"],
                weights=[0.5, 0.3, 0.2],
            )[0]

            device_ip_match = random.random() < 0.15  # rarely matches
            signature_captured = random.random() < 0.3

        




        





