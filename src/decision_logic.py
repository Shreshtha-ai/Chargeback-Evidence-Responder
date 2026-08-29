HIGH_CONFIDENCE_THRESHOLD = 0.75
MEDIUM_CONFIDENCE_THRESHOLD = 0.4
 
 
def apply_confidence_gate(decision: dict) -> dict:
    """
    Takes the agent's decision dict (as returned by agent.investigate_dispute)
    and returns an AUGMENTED COPY with two new fields:
        - gated_action: what the system will actually do (may differ from
          the LLM's own recommended_action if confidence is low)
        - requires_human_review: bool
        - gate_reason: plain-English explanation of why this gate fired
 
    Never mutates the input -- returns a new dict, so the original LLM
    output is preserved untouched for your audit trail / eval comparisons.
    """
    gated = dict(decision)
    confidence = decision.get("confidence", 0)
    llm_recommendation = decision.get("recommended_action", "escalate_to_human")
 
    if "error" in decision:
        # Agent failed to produce a usable decision at all (e.g. couldn't
        # parse its own output, or hit an unrecoverable API error).
        # Always escalate rather than guessing.
        gated["gated_action"] = "escalate_to_human"
        gated["requires_human_review"] = True
        gated["gate_reason"] = "Agent did not produce a valid decision; escalating for manual investigation."
        return gated
 
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        gated["gated_action"] = llm_recommendation
        gated["requires_human_review"] = False
        gated["gate_reason"] = (
            f"Confidence {confidence:.2f} >= {HIGH_CONFIDENCE_THRESHOLD} -- "
            f"proceeding automatically with the agent's recommendation."
        )
    elif confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        gated["gated_action"] = llm_recommendation
        gated["requires_human_review"] = True
        gated["gate_reason"] = (
            f"Confidence {confidence:.2f} is moderate -- drafting the agent's "
            f"recommended response, but flagging for human review before submission."
        )
    else:
        gated["gated_action"] = "concede"
        gated["requires_human_review"] = True
        gated["gate_reason"] = (
            f"Confidence {confidence:.2f} is too low to trust the agent's "
            f"recommendation of '{llm_recommendation}'. Defaulting to 'concede' "
            f"rather than risk wasted effort contesting a dispute we aren't "
            f"confident about, and flagging for human review."
        )
 
    return gated
 
 
if __name__ == "__main__":
    # Quick manual test across three confidence bands, no API calls needed.
    examples = [
        {"predicted_category": "friendly_fraud", "confidence": 0.92,
         "recommended_action": "fight_dispute", "reasoning": "Strong delivery evidence."},
        {"predicted_category": "fraud", "confidence": 0.55,
         "recommended_action": "fight_dispute", "reasoning": "Unfamiliar device, but account is young."},
        {"predicted_category": "merchant_error", "confidence": 0.2,
         "recommended_action": "concede", "reasoning": "Ambiguous signals."},
    ]
    for ex in examples:
        result = apply_confidence_gate(ex)
        print(f"confidence={ex['confidence']} -> gated_action={result['gated_action']}, "
              f"requires_review={result['requires_human_review']}")
        print(f"  reason: {result['gate_reason']}\n")
 
