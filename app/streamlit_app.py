

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from agent import investigate_dispute
from decision_logic import apply_confidence_gate
from evidence_packet import generate_evidence_packet

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

st.set_page_config(page_title="Chargeback Evidence Responder", layout="wide")

st.title("Chargeback Evidence Responder")
st.caption("An agentic system that investigates chargeback disputes step by step and generates a decision with evidence.")


@st.cache_data
def load_disputes():
    disputes = pd.read_csv(os.path.join(DATA_DIR, "disputes.csv"))
    orders = pd.read_csv(os.path.join(DATA_DIR, "orders.csv"))
    return disputes.merge(orders[["order_id", "amount_inr", "item_category"]], on="order_id")


disputes_df = load_disputes()

# --- Sidebar: pick a dispute ---
with st.sidebar:
    st.header("Select a dispute")
    show_ground_truth = st.checkbox("Show ground truth label (demo mode)", value=True)

    options = disputes_df["dispute_id"].tolist()
    labels = {
        row["dispute_id"]: f"{row['dispute_id']} — ₹{row['amount_inr']:.0f} ({row['item_category']})"
        for _, row in disputes_df.iterrows()
    }
    selected_id = st.selectbox("Dispute ID", options, format_func=lambda x: labels[x])

    selected_row = disputes_df[disputes_df["dispute_id"] == selected_id].iloc[0]
    st.write("**Customer claim:**")
    st.info(selected_row["customer_claim_text"])
    st.write(f"**Reason code:** {selected_row['dispute_reason_code']}")
    st.write(f"**Order value:** ₹{selected_row['amount_inr']:.2f}")
    if show_ground_truth:
        st.write(f"**Ground truth (hidden from agent):** `{selected_row['label']}`")

    run_button = st.button("Investigate this dispute", type="primary", use_container_width=True)


# --- Main area: live investigation trace ---
if run_button:
    st.subheader("Investigation in progress")
    trace_container = st.container()
    trace_log = []

    def on_tool_call(tool_name, args, result):
        """Called live by agent.py after each tool executes -- this is
        what makes the investigation visible step by step instead of
        just showing a final answer."""
        trace_log.append((tool_name, args, result))
        with trace_container:
            with st.expander(f"🔧 {tool_name}({args})", expanded=False):
                st.json(result)

    with st.spinner("Agent is investigating..."):
        decision = investigate_dispute(selected_id, verbose=False, on_tool_call=on_tool_call)

    gated = apply_confidence_gate(decision)

    st.subheader("Decision")

    if "error" in decision:
        st.error(f"Investigation did not complete: {decision.get('error')}")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Predicted category", decision["predicted_category"])
        col2.metric("Confidence", f"{decision['confidence']:.0%}")
        col3.metric("System action", gated["gated_action"])

        if gated["requires_human_review"]:
            st.warning(f"⚠️ Requires human review — {gated['gate_reason']}")
        else:
            st.success(f"✅ Auto-approved — {gated['gate_reason']}")

        st.write("**Reasoning:**")
        st.write(decision["reasoning"])

        if show_ground_truth:
            correct = decision["predicted_category"] == selected_row["label"]
            if correct:
                st.success(f"✓ Matches ground truth ({selected_row['label']})")
            else:
                st.error(f"✗ Ground truth was actually: {selected_row['label']}")

        # --- Evidence packet ---
        st.subheader("Generated Evidence Packet")
        packet_path = generate_evidence_packet(selected_id)
        with open(packet_path) as f:
            packet_content = f.read()
        st.markdown(packet_content)
        st.download_button("Download evidence packet (.md)", packet_content, file_name=f"{selected_id}.md")
else:
    st.info("Select a dispute from the sidebar and click **Investigate this dispute** to begin.")