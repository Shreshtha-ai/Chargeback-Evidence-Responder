# Chargeback Evidence Responder

An agentic AI system that investigates e-commerce payment disputes step by step, gathers evidence across multiple data sources, and produces a structured decision with justification — built as an exploration of agentic AI design for fraud/chargeback investigation.

## What this does

When a customer disputes a charge, a merchant has to figure out: is this genuine fraud, "friendly fraud" (a customer disputing a legitimate purchase), or a real mistake on the merchant's side? This project builds an AI agent that investigates a dispute the way a human analyst would — pulling records one at a time, reasoning over what it finds — instead of just running a single classifier and calling it done.

Given a `dispute_id`, the system:
1. Investigates the dispute using 5 tools (order details, delivery proof, customer history, device familiarity, and a structured-feature classifier)
2. Reasons over the retrieved evidence and produces a decision: `fraud`, `friendly_fraud`, or `merchant_error`
3. Applies confidence-gated logic to decide whether to act automatically, flag for human review, or default to a safe fallback
4. Generates a structured evidence packet document from what was actually retrieved — nothing invented

## Why agentic, not just a classifier

A single ML classifier can only output a label. This system treats the classifier as **one input among several**, not the final answer — an LLM agent actively decides what to investigate, in what order, and has to justify its conclusion in plain language grounded in the specific evidence it retrieved. Every tool call is logged, so every decision is auditable after the fact.

## Architecture

```
Dispute comes in
      │
      ▼
┌─────────────┐     calls tools one at a time
│    AGENT    │ ──────────────────────────────┐
│ (agent.py)  │                                │
└─────────────┘                                ▼
      │                                 ┌──────────────┐
      │                                 │    TOOLS     │  reads synthetic
      │                                 │ (tools.py)   │  CSV data
      │                                 └──────────────┘
      │                                        │
      │                                        ▼
      │                                 ┌──────────────┐
      │                                 │  CLASSIFIER  │  one input among
      │                                 │(classifier.py)│  several, not the
      │                                 └──────────────┘  final answer
      ▼
┌─────────────────┐
│ DECISION LOGIC   │  confidence-gated: auto-proceed /
│(decision_logic.py)│  flag for review / safe fallback
└─────────────────┘
      │
      ▼
┌─────────────────┐
│ EVIDENCE PACKET  │  human-readable document, built
│(evidence_packet.py)│ only from actually-retrieved facts
└─────────────────┘
```

## Tech stack

- **Data**: synthetic dataset (Faker), 5 linked CSVs with realistic, correlated (not random) fraud signals
- **Classifier**: scikit-learn GradientBoostingClassifier
- **Agent**: Groq API (`openai/gpt-oss-120b`) with OpenAI-style tool calling
- **UI**: Streamlit (minimal demo interface)
- **Language**: Python

## Project structure

```
chargeback-agent/
├── data/                  # synthetic CSVs + data dictionary
├── src/
│   ├── generate_data.py   # synthetic data generator
│   ├── tools.py           # 5 investigation functions the agent calls
│   ├── classifier.py      # structured-feature model (one tool, not the final answer)
│   ├── agent.py           # the tool-calling investigation loop
│   ├── decision_logic.py  # confidence-gated action policy
│   └── evidence_packet.py # generates the final document from the audit log
├── eval/
│   ├── run_eval.py        # runs the full pipeline on a held-out test set
│   ├── metrics.py         # precision/recall + cost analysis
│   └── eval_summary.md    # final evaluation results
├── app/
│   └── streamlit_app.py   # minimal demo UI
├── logs/
│   ├── audit_trail.jsonl  # every tool call + decision, fully auditable
│   └── packets/           # generated evidence packet documents
└── requirements.txt
```

## Setup

```bash
git clone <this-repo>
cd chargeback-agent
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
GROQ_API_KEY=your_key_here
```
Get a free key at [console.groq.com](https://console.groq.com) — no credit card required.

## Usage

```bash
cd src
python generate_data.py       # generate the synthetic dataset (already included, but reproducible)
python classifier.py          # train the classifier
python agent.py <dispute_id>  # investigate a single dispute
python evidence_packet.py <dispute_id>  # generate its evidence document

cd ../eval
python run_eval.py            # run the full pipeline on the held-out test set
python metrics.py             # compute precision/recall + cost analysis

cd ../app
streamlit run streamlit_app.py  # launch the demo UI
```

## Evaluation results

Evaluated on 22 held-out disputes (20% stratified test split, never seen during classifier training or agent development):

- **21/22 investigations completed (95.5%)**, 1 errored
- **81% label accuracy** (17/21 correct across the 3-way classification)
- **86% action-level accuracy** (18/21 — higher than label accuracy since both `fraud` and `friendly_fraud` correctly route to the same action, `fight_dispute`)
- **Zero missed recoveries** — the system never once failed to contest a dispute with genuine evidence behind it

| Class | Precision | Recall | Support |
|---|---|---|---|
| fraud | 0.60 | 0.75 | 4 |
| friendly_fraud | 0.87 | 1.00 | 13 |
| merchant_error | 1.00 | 0.25 | 4 |

**Cost analysis**: ₹60,270.74 in avoidably-contested disputes (3 `merchant_error` cases wrongly fought), ₹0 in missed recovery. Full breakdown in `eval/eval_summary.md`.

### Known limitation

The agent under-flags `merchant_error` (recall 0.25) — when it does predict merchant_error, it's always correct (precision 1.00), but it tends to default to `fraud` when evidence is mixed rather than considering the merchant may be at fault. This is a documented, understood limitation rather than a silent failure, and reflects a real tradeoff: reducing this would risk increasing missed-recovery cost elsewhere.

## Design decisions worth noting

- **Data leakage prevention**: the dispute's ground-truth label and a customer's `is_repeat_disputer` flag exist in the raw CSVs (for generating realistic correlated data) but are never exposed to any tool the agent can call — the agent has to infer these patterns from plain counts and facts, same as a real investigator would.
- **Device fingerprinting modeled correctly**: an unfamiliar checkout device is only treated as a meaningful fraud signal for an *established* account — a brand-new customer's first order is trivially on an "unknown" device, so penalizing that would unfairly flag every new customer as risky.
- **Confidence gating is separate from the LLM's own reasoning**: `decision_logic.py` is plain, auditable Python — not baked into the prompt — so the exact rule mapping confidence to action can be inspected and reasoned about independently of whatever the model's prompt happens to say.
- **Two real failure modes were found and fixed during evaluation**: a JSON-formatting quirk in the underlying model, and free-tier API rate limiting — both handled with graceful recovery (retry with backoff, in-conversation self-correction) rather than silent failure, reducing the error rate from 23% to 4.5% across the held-out test set.

## Status

This project was built as a learning exercise in agentic AI system design (originally scoped for the Razorpay AI Buildathon, Track 2: AI Risk Manager) and is shared here as-is. The core pipeline — data generation through evaluation — is complete and functional; the UI and further polish were deprioritized due to time constraints.