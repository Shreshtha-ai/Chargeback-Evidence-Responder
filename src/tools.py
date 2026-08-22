# pulls up the order check delivery status

import pandas as pd


#in real system  replace it with db querries 
_customers = pd.read.csv("../data/customers.csv")
_orders = pd.read.csv("../data/orders.csv")
_disputes = pd.read.csv("../data/disputes.csv")
_devices = pd.read.csv("../data/devices.csv")
_deliveries = pd.read.csv("../data/deliveries.csv")

def get_dispute_details(dispute_id: str) -> dict:
    

    
