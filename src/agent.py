"""
agent.py (Groq version)

Same agent design as before -- a tool-calling loop that investigates a
dispute by calling tools.py functions one at a time -- now running on
Groq's free API instead of Gemini's, since Groq's free tier is
significantly more generous (roughly 1,000+ requests/day vs. the 20/day
we hit on Gemini's newer preview model) and uses the well-established
OpenAI-style tool-calling format.

Nothing about the AGENT DESIGN changes: same 5 investigation tools + the
classifier tool, same "classifier is one input, not the answer"
principle, same audit trail, same JSON decision output. Only the API
client/plumbing is different.

Setup:
    pip install groq python-dotenv
    Get a free API key at https://console.groq.com (no credit card)
    Put it in a .env file in your project root:
        GROQ_API_KEY=your_key_here

Model:
    Using llama-3.3-70b-versatile -- a solid, well-supported free-tier
    model for tool-calling tasks. Check console.groq.com/docs/models for
    the current model list if this one is ever deprecated/renamed.
"""

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()  # must run before creating the client, so GROQ_API_KEY is available

from groq import Groq

import tools
from classifier import predict_fraud_likelihood

MODEL = "openai/gpt-oss-120b"  # check console.groq.com/docs/models for current free-tier models
AUDIT_LOG_PATH = "../logs/audit_trail.jsonl"

client = Groq()  # reads GROQ_API_KEY from environment automatically


# ---------------------------------------------------------------------------
# Tool schemas -- OpenAI-compatible "function" format, which Groq uses.
# Same 6 tools as before, just in this format instead of Gemini's or
# Anthropic's. Note the extra {"type": "function", "function": {...}}
# wrapping layer -- that's the OpenAI-style convention.
# ---------------------------------------------------------------------------
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_dispute_details",
            "description": "Look up the raw dispute a customer filed: reason code and their claim text.",
            "parameters": {
                "type": "object",
                "properties": {"dispute_id": {"type": "string"}},
                "required": ["dispute_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": "Look up what was ordered: amount, category, checkout device/IP used at purchase.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_delivery_proof",
            "description": "Look up physical delivery evidence: status, signature captured, delivery photo available.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_history",
            "description": "Look up account-level history: age, past orders, past disputes filed (a plain count, not a verdict).",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_device_familiarity",
            "description": (
                "Check whether a device has been used before for this customer. "
                "Note: an unfamiliar device is only meaningfully suspicious for an "
                "ESTABLISHED account -- a brand-new customer's first order is "
                "trivially on an unfamiliar device, so weigh this alongside "
                "get_customer_history, not in isolation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "device_id": {"type": "string"},
                },
                "required": ["customer_id", "device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_fraud_likelihood",
            "description": (
                "Get a structured-feature model's probability estimate across "
                "{fraud, friendly_fraud, merchant_error} as ONE input to your "
                "reasoning -- not a final answer. You must still justify your "
                "own decision using the actual evidence, not just cite this score."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "is_known_device": {"type": "integer"},
                    "is_established_account": {"type": "integer"},
                    "account_age_days": {"type": "integer"},
                    "past_orders_count": {"type": "integer"},
                    "past_disputes_filed": {"type": "integer"},
                    "signature_captured": {"type": "integer"},
                    "delivery_photo_available": {"type": "integer"},
                    "delivery_status_bad": {"type": "integer"},
                    "amount_inr": {"type": "number"},
                },
                "required": [
                    "is_known_device", "is_established_account", "account_age_days",
                    "past_orders_count", "past_disputes_filed", "signature_captured",
                    "delivery_photo_available", "delivery_status_bad", "amount_inr",
                ],
            },
        },
    },
]

# Maps tool name -> actual Python function that executes it (unchanged from before)
TOOL_DISPATCH = {
    "get_dispute_details": tools.get_dispute_details,
    "get_order_details": tools.get_order_details,
    "get_delivery_proof": tools.get_delivery_proof,
    "get_customer_history": tools.get_customer_history,
    "check_device_familiarity": tools.check_device_familiarity,
    "predict_fraud_likelihood": predict_fraud_likelihood,
}


SYSTEM_PROMPT = """You are a chargeback dispute investigator for an e-commerce merchant.

Given a dispute_id, investigate it using the tools available. Gather
evidence step by step -- don't guess. Consider:
- Is the checkout device/IP familiar for this customer, and is that
  meaningful given their account history? (new device is normal for a
  new account, suspicious for an established one)
- Does the delivery evidence support or contradict the customer's claim?
- Does this customer have a pattern of disputes?

You may call the classifier tool for a structured prior, but your final
decision must be justified from the actual evidence you gathered, in
plain language a non-technical merchant could follow.

When you have enough evidence, respond with your final answer as JSON
(and nothing else) in this exact shape:
{
  "predicted_category": "fraud" | "friendly_fraud" | "merchant_error",
  "confidence": <float 0-1>,
  "recommended_action": "fight_dispute" | "concede" | "escalate_to_human",
  "reasoning": "<2-4 sentence plain-language justification citing the specific evidence you gathered>"
}
"""


def log_audit_entry(dispute_id, tool_calls, final_decision):
    """Appends one line to logs/audit_trail.jsonl -- every tool call made
    and the final decision, so every agent run is independently reviewable."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dispute_id": dispute_id,
        "tool_calls": tool_calls,
        "final_decision": final_decision,
    }
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def investigate_dispute(dispute_id: str, verbose: bool = True) -> dict:
    """
    Runs the full agent loop for one dispute_id using Groq's OpenAI-style
    tool calling. Returns the final decision dict and logs the whole
    investigation to the audit trail.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate dispute_id: {dispute_id}"},
    ]
    tool_call_log = []

    max_turns = 10  # safety cap so a confused model can't loop forever
    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        message = response.choices[0].message

        if not message.tool_calls:
            final_text = message.content
            if verbose:
                print("\n=== Final model output ===")
                print(final_text)
            try:
                cleaned = final_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                decision = json.loads(cleaned)
            except json.JSONDecodeError:
                decision = {"error": "Could not parse model output as JSON", "raw": final_text}
            log_audit_entry(dispute_id, tool_call_log, decision)
            return decision

        # Model's turn (with its tool call requests) goes into history
        messages.append(message)

        # Execute each requested tool call, feed results back as "tool" messages
        for tc in message.tool_calls:
            fn = TOOL_DISPATCH.get(tc.function.name)
            args = json.loads(tc.function.arguments)
            result = fn(**args) if fn else {"error": f"Unknown tool {tc.function.name}"}
            if verbose:
                print(f"[tool call] {tc.function.name}({args}) -> {result}")
            tool_call_log.append({"tool": tc.function.name, "input": args, "output": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    decision = {"error": f"Agent did not converge within {max_turns} turns"}
    log_audit_entry(dispute_id, tool_call_log, decision)
    return decision


if __name__ == "__main__":
    import sys
    import pandas as pd

    if len(sys.argv) > 1:
        test_dispute_id = sys.argv[1]
    else:
        disputes = pd.read_csv("../data/disputes.csv")
        test_dispute_id = disputes.iloc[0]["dispute_id"]

    print(f"Investigating {test_dispute_id}...\n")
    result = investigate_dispute(test_dispute_id)
    print("\n=== Decision ===")
    print(json.dumps(result, indent=2))