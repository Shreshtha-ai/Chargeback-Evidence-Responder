import json
import os
from datetime import datetime
 
from decision_logic import apply_confidence_gate
 
AUDIT_LOG_PATH = "../logs/audit_trail.jsonl"
PACKET_OUTPUT_DIR = "../logs/packets"
 
 
def _load_latest_investigation(dispute_id: str) -> dict:
    """
    Reads the audit trail and returns the MOST RECENT logged investigation
    for this dispute_id (in case the agent was run on it more than once
    while you were testing). Raises a clear error if none is found, so
    you know to run agent.py on this dispute first.
    """
    if not os.path.exists(AUDIT_LOG_PATH):
        raise FileNotFoundError(f"{AUDIT_LOG_PATH} not found -- run agent.py on a dispute first.")
 
    matches = []
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            entry = json.loads(line)
            if entry["dispute_id"] == dispute_id:
                matches.append(entry)
 
    if not matches:
        raise ValueError(
            f"No investigation found for {dispute_id} in {AUDIT_LOG_PATH} -- "
            f"run: python agent.py {dispute_id}"
        )
    return matches[-1]  # most recent, in case it was run more than once
 
 
def _format_evidence_section(tool_calls: list) -> str:
    """
    Turns the raw tool_call_log into a readable evidence section, one
    block per tool actually called. This is what makes the packet
    auditable: every fact in it traces back to a specific retrieved
    tool result, not something the LLM asserted from nowhere.
    """
    lines = []
    for call in tool_calls:
        lines.append(f"**{call['tool']}**")
        for key, value in call["output"].items():
            lines.append(f"  - {key}: {value}")
        lines.append("")
    return "\n".join(lines)
 
 
def generate_evidence_packet(dispute_id: str) -> str:
    """
    Builds the full evidence packet as a Markdown document, saves it to
    logs/packets/{dispute_id}.md, and returns the file path.
    """
    investigation = _load_latest_investigation(dispute_id)
    tool_calls = investigation["tool_calls"]
    decision = investigation["final_decision"]
    gated = apply_confidence_gate(decision)
 
    if "error" in decision:
        body = f"**Investigation did not complete successfully.** Raw output: {decision}\n"
    else:
        body = f"""
## Decision Summary
 
- **Predicted category:** {decision['predicted_category']}
- **Model confidence:** {decision['confidence']}
- **System action:** {gated['gated_action']} {"(requires human review)" if gated['requires_human_review'] else "(auto-approved, no review needed)"}
- **Gating rationale:** {gated['gate_reason']}
 
## Reasoning
 
{decision['reasoning']}
 
## Supporting Evidence
 
{_format_evidence_section(tool_calls)}
"""
 
    packet = f"""# Chargeback Evidence Packet
 
**Dispute ID:** {dispute_id}
**Generated:** {datetime.now().isoformat()}
{body}
---
*This packet was generated automatically from evidence retrieved during an
agent investigation. Every fact above traces back to a logged tool call in
the audit trail -- nothing here was inferred without a retrievable source.*
"""
 
    os.makedirs(PACKET_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(PACKET_OUTPUT_DIR, f"{dispute_id}.md")
    with open(out_path, "w") as f:
        f.write(packet)
 
    return out_path
 
 
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python evidence_packet.py <dispute_id>")
        sys.exit(1)
 
    path = generate_evidence_packet(sys.argv[1])
    print(f"Evidence packet written to {path}\n")
    with open(path) as f:
        print("--- Packet contents ---\n")
        print(f.read())
 
