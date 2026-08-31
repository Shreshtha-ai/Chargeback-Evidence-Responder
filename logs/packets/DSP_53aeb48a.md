# Chargeback Evidence Packet
 
**Dispute ID:** DSP_53aeb48a
**Generated:** 2026-08-31T12:46:34.458602

## Decision Summary
 
- **Predicted category:** friendly_fraud
- **Model confidence:** 0.85
- **System action:** fight_dispute (auto-approved, no review needed)
- **Gating rationale:** Confidence 0.85 >= 0.75 -- proceeding automatically with the agent's recommendation.
 
## Reasoning
 
The purchase was made on a known device that the customer has used multiple times, and the account is over three years old with no prior disputes. Delivery evidence shows the order was signed for and a delivery photo exists, indicating the item was received as shipped. The claim of "not as described" is vague and there is no contradictory evidence, making a fraudulent chargeback more likely than a genuine merchant error.
 
## Supporting Evidence
 
**get_dispute_details**
  - dispute_id: DSP_53aeb48a
  - order_id: ORD_3f095512
  - dispute_date: 2026-08-07T07:20:09.506572
  - dispute_reason_code: not_as_described
  - customer_claim_text: This does not match what I ordered, I want my money back.

**get_order_details**
  - order_id: ORD_3f095512
  - customer_id: CUST_444fa0bd
  - order_timestamp: 2026-08-01T07:20:09.506572
  - amount_inr: 15167.87
  - item_category: Fashion
  - checkout_ip: 89.124.156.88
  - checkout_device_id: DEV_e6f07bde6d

**get_delivery_proof**
  - order_id: ORD_3f095512
  - delivery_status: delivered
  - delivery_timestamp: 2026-08-06T07:20:09.506572
  - signature_captured: True
  - delivery_photo_available: True

**get_customer_history**
  - customer_id: CUST_444fa0bd
  - account_age_days: 1227
  - past_orders_count: 1
  - past_disputes_filed: 0

**check_device_familiarity**
  - customer_id: CUST_444fa0bd
  - device_id: DEV_e6f07bde6d
  - is_known_device: True
  - times_used: 5
  - first_seen_date: 2025-02-24T21:20:09.473634

**predict_fraud_likelihood**
  - fraud: 0.0
  - friendly_fraud: 1.0
  - merchant_error: 0.0


---
*This packet was generated automatically from evidence retrieved during an
agent investigation. Every fact above traces back to a logged tool call in
the audit trail -- nothing here was inferred without a retrievable source.*
