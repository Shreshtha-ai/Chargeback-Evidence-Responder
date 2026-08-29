"""
run_eval.py

Runs the full agent pipeline (investigate -> confidence gate) across a
HELD-OUT test set of disputes -- the same disputes the classifier never
trained on -- and saves the raw per-dispute results to eval_results.json.

Uses the EXACT SAME 80/20 stratified split as classifier.py (identical
seed=42), so the classifier's reported metrics and the agent's reported
metrics are directly comparable: both evaluated on the identical unseen
disputes, not two different test sets that happen to look similar.

Why this is a separate script from metrics.py:
-------------------------------------------------
Running the agent costs real API calls (time + free-tier quota). You
don't want to burn that quota every time you tweak how a metric is
calculated. This script runs the agent ONCE and saves raw results;
metrics.py then computes precision/recall/cost analysis from the saved
file as many times as you want, for free, without re-calling the API.
"""

import json
import time
import sys
import os

import pandas as pd
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from agent import investigate_dispute
from decision_logic import apply_confidence_gate
from classifier import build_feature_table, FEATURE_COLS, DATA_DIR

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_results.json")
SLEEP_BETWEEN_CALLS = 2  # seconds -- be polite to the free-tier API, avoid rate limits


def get_test_dispute_ids():
    """
    Reproduces the EXACT same 80/20 stratified split classifier.py uses
    (same seed, same stratify column), so the agent is evaluated on the
    identical held-out disputes as the classifier -- apples to apples.
    """
    df = build_feature_table()
    X = df[FEATURE_COLS]
    y = df["label"]
    _, X_test, _, _ = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    return df.loc[X_test.index, "dispute_id"].tolist()


def _investigate_with_retry(dispute_id: str, max_attempts: int = 2) -> dict:
    """
    Runs investigate_dispute() and validates the result actually has the
    fields we need. A model call can "succeed" (no exception) but still
    return incomplete JSON -- e.g. missing predicted_category -- which is
    a real failure for eval purposes even though nothing crashed. This
    wrapper catches BOTH crash-failures and silent incomplete-output
    failures, and retries once before giving up, since a single flaky
    generation shouldn't cost you an entire test case.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            decision = investigate_dispute(dispute_id, verbose=False)
            gated = apply_confidence_gate(decision)
            # A usable decision MUST have predicted_category and confidence.
            # If either is missing, treat it as a failure even though no
            # exception was raised -- this is the bug we caught by hand
            # the first time (silent "ERROR" that wasn't counted).
            if gated.get("predicted_category") and gated.get("confidence") is not None:
                return gated
            last_error = f"Incomplete model output (missing required fields): {decision}"
        except Exception as e:
            last_error = str(e)

        if attempt < max_attempts:
            time.sleep(SLEEP_BETWEEN_CALLS)  # brief pause before retrying

    return {"error": last_error}


def run_eval(limit: int = None):
    """
    Runs the agent on each held-out test dispute. `limit` lets you run a
    quick partial eval (e.g. limit=5) to sanity-check everything works
    before committing your full free-tier quota to a complete run.
    """
    test_ids = get_test_dispute_ids()
    if limit:
        test_ids = test_ids[:limit]

    disputes = pd.read_csv(os.path.join(DATA_DIR, "disputes.csv")).set_index("dispute_id")
    orders = pd.read_csv(os.path.join(DATA_DIR, "orders.csv")).set_index("order_id")

    results = []
    print(f"Running agent on {len(test_ids)} held-out disputes...\n")

    for i, dispute_id in enumerate(test_ids, 1):
        true_label = disputes.loc[dispute_id, "label"]
        order_id = disputes.loc[dispute_id, "order_id"]
        amount = float(orders.loc[order_id, "amount_inr"])

        print(f"[{i}/{len(test_ids)}] {dispute_id} (true: {true_label})...", end=" ", flush=True)

        gated = _investigate_with_retry(dispute_id)
        print(f"predicted: {gated.get('predicted_category') or 'ERROR'}")

        results.append({
            "dispute_id": dispute_id,
            "true_label": true_label,
            "amount_inr": amount,
            "predicted_category": gated.get("predicted_category"),
            "confidence": gated.get("confidence"),
            "gated_action": gated.get("gated_action"),
            "requires_human_review": gated.get("requires_human_review"),
            "error": gated.get("error"),
        })

        time.sleep(SLEEP_BETWEEN_CALLS)

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

    n_errors = sum(1 for r in results if r["error"])
    print(f"\nDone. {len(results) - n_errors}/{len(results)} completed successfully, {n_errors} errored.")
    print(f"Raw results saved to {RESULTS_PATH}")
    return results


if __name__ == "__main__":
    # Usage: python run_eval.py           -> full held-out test set
    #        python run_eval.py 5         -> quick partial run, first 5 only
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_eval(limit=limit)