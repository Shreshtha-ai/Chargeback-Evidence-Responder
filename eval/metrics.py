

import json
import os

from sklearn.metrics import classification_report, confusion_matrix

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_results.json")
METRICS_OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics_report.json")


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def compute_classification_metrics(results):
    
    completed = [r for r in results if r["predicted_category"]]
    errored = [r for r in results if not r["predicted_category"]]

    y_true = [r["true_label"] for r in completed]
    y_pred = [r["predicted_category"] for r in completed]

    report = classification_report(y_true, y_pred, zero_division=0, output_dict=True)
    labels = sorted(set(y_true) | set(y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=labels).tolist()

    return {
        "total_disputes": len(results),
        "completed": len(completed),
        "errored": len(errored),
        "error_rate": round(len(errored) / len(results), 3) if results else 0,
        "classification_report": report,
        "confusion_matrix": {"labels": labels, "matrix": cm},
        "errored_dispute_ids": [r["dispute_id"] for r in errored],
    }


def compute_cost_analysis(results):
    
    completed = [r for r in results if r["predicted_category"]]

    should_fight_labels = {"fraud", "friendly_fraud"}   # real evidence exists to contest these
    should_concede_labels = {"merchant_error"}           # merchant was actually at fault

    counts = {"correct_fight": 0, "correct_concede": 0, "wasted_fight": 0, "missed_recovery": 0, "deferred": 0}
    wasted_fight_amount = 0.0
    missed_recovery_amount = 0.0

    for r in completed:
        action = r.get("gated_action")
        true_label = r["true_label"]
        amount = r.get("amount_inr", 0)

        if action == "escalate_to_human":
            counts["deferred"] += 1
        elif action == "fight_dispute":
            if true_label in should_fight_labels:
                counts["correct_fight"] += 1
            else:
                counts["wasted_fight"] += 1
                wasted_fight_amount += amount
        elif action == "concede":
            if true_label in should_concede_labels:
                counts["correct_concede"] += 1
            else:
                counts["missed_recovery"] += 1
                missed_recovery_amount += amount

    return {
        "outcome_counts": counts,
        "wasted_fight_amount_inr": round(wasted_fight_amount, 2),
        "missed_recovery_amount_inr": round(missed_recovery_amount, 2),
        "net_avoidable_cost_inr": round(wasted_fight_amount + missed_recovery_amount, 2),
    }


def main():
    results = load_results()
    classification = compute_classification_metrics(results)
    cost = compute_cost_analysis(results)
    report = {"classification_metrics": classification, "cost_analysis": cost}

    with open(METRICS_OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print("=== Classification metrics (scored on completed disputes only) ===")
    print(f"Completed: {classification['completed']}/{classification['total_disputes']} "
          f"  |  Error rate: {classification['error_rate']*100:.1f}%")
    if classification["errored_dispute_ids"]:
        print(f"Errored dispute IDs: {classification['errored_dispute_ids']}")
    print()
    for label, scores in classification["classification_report"].items():
        if isinstance(scores, dict):
            print(f"{label:20s} precision={scores['precision']:.2f}  recall={scores['recall']:.2f}  "
                  f"f1={scores['f1-score']:.2f}  support={int(scores['support'])}")
    print()
    print("Confusion matrix (rows=true, cols=predicted):")
    print("labels:", classification["confusion_matrix"]["labels"])
    for row in classification["confusion_matrix"]["matrix"]:
        print(" ", row)
    print()
    print("=== Cost analysis ===")
    print(json.dumps(cost, indent=2))
    print()
    print(f"Full report saved to {METRICS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()