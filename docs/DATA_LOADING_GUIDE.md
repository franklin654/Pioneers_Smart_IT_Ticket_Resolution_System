# Data Loading & Classifier Training Guide

**Working directory for all commands:** `backend/`

---

## Prerequisites

- Database initialised (`python -m scripts.setup_db`)
- Python environment active with dependencies installed (`pip install -e ".[dev]"`)
- `.env` configured with a valid `DATABASE_URL` and `ANTHROPIC_API_KEY`

---

## Step 1 — Generate training data

Uses the Claude API to produce balanced synthetic IT support tickets across all 6 categories.

```bash
python -m scripts.generate_synthetic_data \
  --mode train \
  --count 1200 \
  --output data/raw/synthetic_train.csv
```

This generates **200 tickets per category** (1,200 total) using `CATEGORY_SCENARIOS` — realistic enterprise IT issues with title, description, category, resolution, and priority columns.

**Optional flags:**

```bash
# Fewer tickets for a quick test run
python -m scripts.generate_synthetic_data --mode train --count 120 --output data/raw/synthetic_train.csv

# Only specific categories
python -m scripts.generate_synthetic_data --mode train --count 600 \
  --categories security,network,database --output data/raw/synthetic_train.csv
```

---

## Step 2 — Load training data

```bash
python -m scripts.load_tickets \
  --input-path data/raw/synthetic_train.csv \
  --source synthetic_train
```

Inserts rows as `TicketSource.CSV` tickets **and** into `knowledge_base_entries` (because training CSVs have a `resolution` column). The KB entries are what the RAG retriever queries at inference time.

Safe to re-run — duplicate rows are skipped via SHA-256 content hash.

---

## Step 3 — Generate held-out test set

```bash
python -m scripts.generate_synthetic_data \
  --mode test \
  --count 300 \
  --output data/raw/synthetic_test.csv
```

Generates **50 tickets per category** (300 total) using `TEST_CATEGORY_SCENARIOS` — harder, more specific edge cases (e.g. "BGP route flapping destabilising upstream peering", "autovacuum not running on heavily bloated tables"). The test CSV has **no resolution column** — these are unseen problems the classifier and RAG pipeline must solve cold.

---

## Step 4 — Load held-out test set

```bash
python -m scripts.load_tickets \
  --input-path data/raw/synthetic_test.csv \
  --ticket-source webhook \
  --source synthetic_test
```

The `--ticket-source webhook` flag tags tickets as `TicketSource.WEBHOOK`, which is how `evaluation/routing_accuracy_eval.py` isolates them from training data. No KB entries are created (no resolution column → nothing to index).

---

## Step 5 — Train the classifier

Reads all labeled tickets (`TicketSource.CSV`) from the database, generates embeddings, trains a LinearSVC (CalibratedClassifierCV) model, and saves the artifact.

```bash
python -m scripts.train_classifier
```

**Expected output:**

```text
  Accuracy:       0.94+
  Macro F1:       0.92+
  Train samples:  ~960
  Test samples:   ~240
  Model saved to: data/models/classifier.pkl
```

Gate: macro F1 ≥ 0.90. The script exits with code 1 if below target.

**Optional flags:**

```bash
# Increase regularization if overfitting
python -m scripts.train_classifier --c 2.0

# Use a larger test split
python -m scripts.train_classifier --test-size 0.25
```

---

## Step 6 — Index the knowledge base

Builds the BM25 index from all `KnowledgeBaseEntry` rows loaded in Step 2.

```bash
python -m scripts.index_knowledge_base
```

---

## Step 7 — Verify

```bash
# Start the API
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Confirm health
curl http://localhost:8000/health/ready
# → {"status":"ready","database":"ok"}

# Quick classifier smoke test — submit a ticket
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=$ADMIN_PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/api/v1/tickets/ingest \
     -d '{"title":"VPN auth failure","description":"Cannot connect to corporate VPN from home since this morning.","priority":2}'
```

---

## Step 8 — Run the full evaluation suite

Requires the API to have processed some tickets first (Step 7 above).

```bash
python -m evaluation.run_all \
  --fail-under-f1 0.92 \
  --fail-under-llm 3.5 \
  --fail-latency 5.0 \
  --fail-auto-resolve 25.0 \
  --fail-under-routing 0.75
```

To run just the routing accuracy evaluator against the held-out test set (after the webhook-tagged tickets have been processed through the pipeline):

```bash
python -m evaluation.routing_accuracy_eval --fail-under 0.75
```

---

## Summary of data volumes

| Source | Rows | IT-labeled | Notes |
| --- | --- | --- | --- |
| Synthetic training (`--mode train`) | ~1,200 | 1,200 | All 6 categories, balanced, includes resolutions |
| Synthetic test set (`--mode test`) | ~300 | 300 | Harder edge cases, no resolutions, held-out |
| **Total training** | **~1,200** | **~1,200** | All rows are fully labeled |
| Held-out (routing eval) | 300 | 300 | `TicketSource.WEBHOOK` — never used for training |
