# Data Loading & Classifier Training Guide

**Working directory for all commands:** `app_v2/backend/`

---

## Prerequisites

- Database initialised (`python -m scripts.setup_db` — already done)
- Conda environment active with dependencies installed (`pip install -e ".[dev]"`)
- `.env` configured with a valid `DATABASE_URL`

---

## Step 1 — Download the datasets

Place all downloaded files under `app_v2/backend/data/raw/`.

| # | Dataset | Source | Expected filename |
| --- | --- | --- | --- |
| 1 | IT Support Ticket Classification (SKIPPED) | kaggle.com/datasets/suraj520/it-support-ticket-classification | Dataset no longer available on Kaggle |
| 2 | Customer Support Ticket Dataset | kaggle.com/datasets/suraj520/customer-support-ticket-dataset | `kaggle_customer_support.csv` |
| 3 | Automatic Ticket Classification (SKIPPED) | kaggle.com/datasets/venkatasubramanian/automatic-ticket-classification | Financial domain — no IT category labels, do not load |
| 4 | IT Service Ticket Classification | kaggle.com/datasets/adisongoh/it-service-ticket-classification-dataset | `kaggle_it_service.csv` |
| 5 | IT Support Ticket Data (parthpatil) | kaggle.com/datasets/parthpatil256/it-support-ticket-data | `kaggle_parthpatil.csv` |
| 6 | Multilingual Customer Support | kaggle.com/datasets/tobiasbueck/multilingual-customer-support-tickets | `multilingual.csv` |
| 7 | Bitext LLM Training Dataset (SKIPPED) | huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset | E-commerce categories only (ORDER/REFUND/INVOICE) — no IT labels, do not load |
| 8 | UCI Incident Management Log (SKIPPED) | archive.ics.uci.edu/ml/datasets/Incident+management+process+enriched+event+log | Fully anonymized ("Category 26", "Symptom 72") — no usable text content, do not load |
| 9 | 6StringNinja ServiceNow (test set) | huggingface.co/datasets/6StringNinja/synthetic-servicenow-incidents | `servicenow_test.parquet` |

**Tip — Kaggle CLI download:**

```bash
pip install kaggle          # one-time
kaggle datasets download -d suraj520/customer-support-ticket-dataset -p data/raw/ --unzip
kaggle datasets download -d adisongoh/it-service-ticket-classification-dataset -p data/raw/ --unzip
kaggle datasets download -d parthpatil256/it-support-ticket-data -p data/raw/ --unzip
kaggle datasets download -d tobiasbueck/multilingual-customer-support-tickets -p data/raw/ --unzip
```

**Tip — HuggingFace download:**

```python
from huggingface_hub import hf_hub_download
hf_hub_download(repo_id="bitext/Bitext-customer-support-llm-chatbot-training-dataset",
                filename="train.parquet", repo_type="dataset",
                local_dir="data/raw/")
# rename to bitext.parquet
```

---

## Step 2 — (Optional) Generate synthetic data

Requires `ANTHROPIC_API_KEY` set in `.env`. Skip if you have enough Kaggle data.

```bash
python -m scripts.generate_synthetic_data \
  --count 1000 \
  --output data/raw/synthetic.csv
```

---

## Step 3 — Load training data

Run each command from `app_v2/backend/`. Safe to re-run — duplicate rows are skipped via content hash.

### 3a. Synthetic data (if generated)

```bash
python -m scripts.load_kaggle_data \
  --input-path data/raw/synthetic.csv \
  --source synthetic
```

### 3b. Kaggle: Customer Support Dataset (~8.5K)

```bash
python -m scripts.load_kaggle_data \
  --input-path data/raw/kaggle_customer_support.csv \
  --source kaggle_customer_support
```

### 3c. Kaggle: IT Service Ticket Classification (~47K)

```bash
python -m scripts.load_kaggle_data \
  --input-path data/raw/kaggle_it_service.csv \
  --source kaggle_it_service
```

### 3d. Kaggle: IT Support Ticket Data — parthpatil (~29K, no title column)

This dataset has only a `Body` column — the loader automatically uses the first 150 chars as the title.

```bash
python -m scripts.load_kaggle_data \
  --input-path data/raw/kaggle_parthpatil.csv \
  --source kaggle_parthpatil
```

### 3e. Kaggle: Multilingual Customer Support (English only, ~16K)

```bash
python -m scripts.load_kaggle_data \
  --input-path data/raw/multilingual.csv \
  --language en \
  --source multilingual
```

### 3f. 6StringNinja ServiceNow test set (500 rows — held-out, not training)

**Load last.** These 500 rows are for evaluation only and are never mixed with training data.

```bash
python -m scripts.load_servicenow_test_set \
  --input-path data/raw/servicenow_test.parquet
```

---

## Step 4 — Train the classifier

Reads all labeled tickets from the database, generates embeddings, trains a LogisticRegression model, and saves the artifact.

```bash
python -m scripts.train_classifier
```

**Expected output:**

```text
  Accuracy:       0.9412
  Macro F1:       0.9387
  Train samples:  ~90,000
  Test samples:   ~22,000
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

## Step 5 — Index the knowledge base

Builds the BM25 index from all `KnowledgeBaseEntry` rows loaded in Step 3.

```bash
python -m scripts.index_knowledge_base
```

---

## Step 6 — Verify

```bash
# Start the API
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Confirm health
curl http://localhost:8000/health/ready
# → {"status":"ready","database":"ok"}

# Quick classifier smoke test — submit a ticket
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=changeme123" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/api/v1/tickets/ingest \
     -d '{"title":"VPN auth failure","description":"Cannot connect to corporate VPN from home since this morning.","priority":2}'
```

---

## Step 7 — Run the full evaluation suite

Requires the API to have processed some tickets first (Step 6 above).

```bash
python -m evaluation.run_all
```

To run just the routing accuracy evaluator against the held-out ServiceNow test set (after processing those 500 tickets through the pipeline):

```bash
python -m evaluation.routing_accuracy_eval --fail-under 0.75
```

---

## Summary of expected data volumes

| Source | Rows | IT-labeled | Notes |
| --- | --- | --- | --- |
| Synthetic (optional) | ~1,000 | ~1,000 | All labeled |
| Kaggle Customer Support | ~8,500 | partial | Ticket Type → category |
| Kaggle IT Service | ~47,800 | ~23,000 | Hardware/Access/Storage labeled; HR/Misc skipped |
| Kaggle parthpatil | ~29,600 | ~12,000 | Tech Support + IT Support labeled; rest null |
| Multilingual (EN) | ~16,300 | ~12,000 | Technical Support + IT Support labeled |
| Kaggle IT Support | — | — | SKIPPED — no longer available on Kaggle |
| Bitext | — | — | SKIPPED — e-commerce categories only |
| UCI Incidents | — | — | SKIPPED — fully anonymized data |
| **Total training** | **~103,000** | **~48,000+** | Labeled tickets train the classifier |
| 6StringNinja (test set) | 500 | 500 | Held-out evaluation only |
