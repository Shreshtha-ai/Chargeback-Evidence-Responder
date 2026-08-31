

import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()  # must run before creating the client, so GROQ_API_KEY is available

from groq import Groq
from groq import BadRequestError, RateLimitError

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
(and nothing else) in this exact shape. Do NOT call a tool to produce
this answer -- just write the JSON directly as your plain text response:
{
  "predicted_category": "fraud" | "friendly_fraud" | "merchant_error",
  "confidence": <float 0-1>,
  "recommended_action": "fight_dispute" | "concede" | "escalate_to_human",
  "reasoning": "<2-4 sentence plain-language justification citing the specific evidence you gathered>"
}
"""


REQUIRED_DECISION_FIELDS = ["predicted_category", "confidence", "recommended_action", "reasoning"]


def _is_complete_decision(decision: dict) -> bool:
    """A usable decision must have all four required fields. Used both to
    decide whether to nudge the model for a correction, and later by
    run_eval.py's retry logic to decide whether a whole re-investigation
    is needed."""
    return all(k in decision for k in REQUIRED_DECISION_FIELDS)


def _extract_json_decision(final_text: str) -> dict:
    """
    Parses the model's final answer as JSON, with two fallback layers
    before giving up -- this is a common LLM failure mode: instructed to
    "output ONLY JSON," models sometimes still add a stray sentence
    before/after it, or wrap it in markdown code fences.

    Layer 1: strip markdown fences, try direct parse.
    Layer 2: if that fails, search for the first {...} block anywhere in
              the text using a brace-matching scan (handles nested braces
              correctly, unlike a naive regex).
    If both fail, return an error dict -- this is what run_eval.py's
    retry logic checks for and retries on.
    """
    if not final_text:
        return {"error": "Model returned empty output"}

    cleaned = final_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: scan for the first balanced {...} block anywhere in the text
    start = final_text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(final_text)):
            if final_text[i] == "{":
                depth += 1
            elif final_text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = final_text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    return {"error": "Could not parse model output as JSON", "raw": final_text}


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


def _call_with_rate_limit_retry(max_retries: int = 3, **kwargs):
    """
    Wraps client.chat.completions.create() with automatic backoff on
    genuine rate-limit errors (HTTP 429). This is different from the
    JSON-recovery logic below -- a rate limit is a TRANSIENT condition
    that resolves itself if you just wait, so it deserves a real retry
    with a pause, not an immediate failure. Without this, a burst of
    6-7 rapid calls within a single investigation (no delay between
    tool-calling turns) can trip Groq's free-tier per-minute limit and
    kill the whole investigation on one unlucky call.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            if attempt == max_retries:
                raise
            wait_seconds = 15 * attempt  # back off progressively: 15s, 30s
            print(f"[rate limited] waiting {wait_seconds}s before retry {attempt+1}/{max_retries}...")
            time.sleep(wait_seconds)


def investigate_dispute(dispute_id: str, verbose: bool = True, on_tool_call=None) -> dict:
    """
    Runs the full agent loop for one dispute_id using Groq's OpenAI-style
    tool calling. Returns the final decision dict and logs the whole
    investigation to the audit trail.

    on_tool_call: optional callback, called as on_tool_call(tool_name, args, result)
    immediately after each tool executes. This lets a UI (e.g. the
    Streamlit app) show the investigation happening live, tool by tool,
    instead of only seeing the final decision once everything is done.
    Purely additive -- agent.py's own CLI usage is unaffected since this
    defaults to None.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate dispute_id: {dispute_id}"},
    ]
    tool_call_log = []
    corrected = False  # tracks whether we've already given the model one corrective nudge

    max_turns = 10  # safety cap so a confused model can't loop forever
    for _ in range(max_turns):
        try:
            response = _call_with_rate_limit_retry(
                model=MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except BadRequestError as e:
            # Known GPT-OSS quirk on Groq: the model sometimes tries to call a
            # fake "json" tool to structure its final answer instead of just
            # writing plain text. Groq rejects the request, but the intended
            # answer is still recoverable from the error body's
            # "failed_generation" field -- so we extract it instead of crashing.
            body = getattr(e, "body", None) or {}
            failed_generation = body.get("error", {}).get("failed_generation")
            if failed_generation:
                try:
                    parsed = json.loads(failed_generation)
                    decision = parsed.get("arguments", parsed)
                    if verbose:
                        print("\n=== Recovered final answer from a rejected tool call ===")
                        print(json.dumps(decision, indent=2))
                    log_audit_entry(dispute_id, tool_call_log, decision)
                    return decision
                except json.JSONDecodeError:
                    pass
            raise
        message = response.choices[0].message

        if not message.tool_calls:
            final_text = message.content
            if verbose:
                print("\n=== Final model output ===")
                print(final_text)
            decision = _extract_json_decision(final_text)

            if _is_complete_decision(decision):
                log_audit_entry(dispute_id, tool_call_log, decision)
                return decision

            # The model finished (no more tool calls) but didn't produce a
            # usable decision -- e.g. it emitted a stray fragment like
            # {"customer_id": "..."} instead of the real JSON answer, which
            # looks like a leftover piece of a tool call that never got
            # registered properly. Rather than giving up immediately, give
            # the model ONE corrective nudge in the SAME conversation (it
            # still has all the evidence gathered so far) before falling
            # back to reporting an error.
            if not corrected:
                if verbose:
                    print("[recovering] final output was incomplete, asking model to correct it...")
                messages.append(message)
                messages.append({
                    "role": "user",
                    "content": (
                        "Your last response was not a complete answer. Respond with "
                        "ONLY a JSON object containing exactly these keys: "
                        "predicted_category, confidence, recommended_action, reasoning."
                    ),
                })
                corrected = True
                continue

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
            if on_tool_call:
                on_tool_call(tc.function.name, args, result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

        # Small pacing delay between turns -- each investigation makes several
        # rapid successive API calls (one per tool-calling round), and without
        # any gap between them, a burst of 6-7 calls can trip Groq's
        # free-tier per-minute rate limit even before the RESULT of any one
        # call is a problem. This just spreads the calls out slightly.
        time.sleep(1)

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