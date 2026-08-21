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

def random_date(start_days_ago =100, end_days_ago =0): #used to generate random  transaction/order timestamps 
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

def generate_orders(customers,n):
    orders = []
    for _ in range(n):
        cust = random.choice(customers)
        checkout_ip = fake.ipv4()
        orders.append({
            "order_id": f"ORD_{uuid.uuid4().hex[:8]}",
            "customer_id": cust["customer_id"],
            "amount_inr": round(random.uniform(150, 25000),2),
            "order_timestamp": random_date().isoformat(), #used to generate ISO format
            "checkout_ip": checkout_ip,
            "checkout_device_id" : f"DEV_{uuid.uuid4().hex[:8]}",
            
            
        })
    return orders


        





