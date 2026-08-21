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





