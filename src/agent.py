"""
agent.py (Gemini version)

Same agent design as before -- tool-calling loop that investigates a
dispute by calling tools.py functions one at a time -- just running on
Google's Gemini API instead of Anthropic's, since Gemini's Flash models
have a genuine free tier (Anthropic's API is pay-per-token with only a
one-time trial credit, which may not be available on all accounts).

Nothing about the AGENT DESIGN changes: same 5 investigation tools, same
"classifier is one input, not the answer" principle, same audit trail,
same JSON decision output. Only the API client/plumbing is different.

Setup:
    pip install google-genai python-dotenv
    Get a free API key at https://aistudio.google.com (no credit card)
    Put it in a .env file in your project root:
        GEMINI_API_KEY=your_key_here

Model:
    Free tier currently covers Gemini's "Flash" and "Flash-Lite" models
    (Pro models are paid-only as of April 2026). Check aistudio.google.com
    for the exact current free model name before running -- model names
    get versioned/renamed over time, so MODEL below may need updating.
"""

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()  # must run before creating the client, so GEMINI_API_KEY is available

from google import genai
from google.genai import types

import tools
from classifier import predict_fraud_likelihood

MODEL = "gemini-3.6-flash"  # check aistudio.google.com for the current free-tier model name
AUDIT_LOG_PATH = "../logs/audit_trail.jsonl"

client = genai.Client()  # reads GEMINI_API_KEY from environment automatically


# ---------------------------------------------------------------------------
# Tool schemas -- same 6 tools as the Anthropic version, just in Gemini's
# function-declaration format instead of Anthropic's input_schema format.
# ---------------------------------------------------------------------------
FUNCTION_DECLARATIONS = [
    {
        "name": "get_dispute_details",
        "description": "Look up the raw dispute a customer filed: reason code and their claim text.",
        "parameters": {
            "type": "object",
            "properties": {"dispute_id": {"type": "string"}},
            "required": ["dispute_id"],
        },
    },
    {
        "name": "get_order_details",
        "description": "Look up what was ordered: amount, category, checkout device/IP used at purchase.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_delivery_proof",
        "description": "Look up physical delivery evidence: status, signature captured, delivery photo available.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_customer_history",
        "description": "Look up account-level history: age, past orders, past disputes filed (a plain count, not a verdict).",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
    },
    {
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
    {
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
]

GEMINI_TOOL = types.Tool(function_declarations=FUNCTION_DECLARATIONS)

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
    Runs the full agent loop for one dispute_id using Gemini's function
    calling. Returns the final decision dict and logs the whole
    investigation to the audit trail.
    """
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=f"Investigate dispute_id: {dispute_id}")])
    ]
    tool_call_log = []

    config = types.GenerateContentConfig(
        tools=[GEMINI_TOOL],
        system_instruction=SYSTEM_PROMPT,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    max_turns = 10  # safety cap so a confused model can't loop forever
    for _ in range(max_turns):
        response = client.models.generate_content(model=MODEL, contents=contents, config=config)

        function_calls = response.function_calls
        if not function_calls:
            final_text = response.text
            if verbose:
                print("\n=== Final model output ===")
                print(final_text)
            try:
                # strip markdown code fences if the model wraps its JSON in ```json ... ```
                cleaned = final_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                decision = json.loads(cleaned)
            except json.JSONDecodeError:
                decision = {"error": "Could not parse model output as JSON", "raw": final_text}
            log_audit_entry(dispute_id, tool_call_log, decision)
            return decision

        # Model's turn (containing the function call requests) goes into history
        contents.append(response.candidates[0].content)

        # Execute each requested tool call, build function_response parts
        response_parts = []
        for fc in function_calls:
            fn = TOOL_DISPATCH.get(fc.name)
            result = fn(**fc.args) if fn else {"error": f"Unknown tool {fc.name}"}
            if verbose:
                print(f"[tool call] {fc.name}({dict(fc.args)}) -> {result}")
            tool_call_log.append({"tool": fc.name, "input": dict(fc.args), "output": result})
            response_parts.append(types.Part.from_function_response(name=fc.name, response=result))

        contents.append(types.Content(role="user", parts=response_parts))

    # Safety net: exceeded max_turns without a final answer
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