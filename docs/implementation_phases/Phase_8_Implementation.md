# Phase 8 — Evaluation Suite (Completed)

**Project root:** `app_v2/backend/`
**Status:** Complete — all scripts implemented, syntax/import verified

---

## What Was Built

Phase 8 delivers a reproducible evaluation suite that validates all six target metrics before the demo. Two evaluators were already present; this phase added the two missing ones and a unified runner.

---

## Target Metrics

| Metric | Target | Evaluator | Status |
| --- | --- | --- | --- |
| Classification Macro F1 | ≥ 0.92 | `classification_eval.py` | Existing |
| RAG Precision@5 | ≥ 0.80 | `rag_eval.py` | Existing |
| RAG MRR | ≥ 0.70 | `rag_eval.py` | Existing |
| LLM Quality Score (mean) | ≥ 3.5/5 | `llm_judge.py` | **New** |
| Auto-Resolve Rate | ≥ 25% | `end_to_end_eval.py` | **New** |
| E2E Latency p95 | < 5s | `end_to_end_eval.py` | **New** |

---

## Files Created / Modified

```text
evaluation/
├── classification_eval.py   EXISTING — unchanged
├── rag_eval.py              EXISTING — unchanged
├── llm_judge.py             NEW — LLM quality score distribution
├── end_to_end_eval.py       NEW — E2E latency + routing distribution
└── run_all.py               NEW — unified runner for all four

src/db/repositories/
└── resolution_repo.py       MODIFIED — added get_all_with_quality_scores()
```

---

## 1. `evaluation/classification_eval.py` (Existing)

Loads the trained `TicketClassifier` artifact, runs it against all labeled tickets in the DB, and reports F1 / precision / recall per category plus a confusion matrix PNG.

**CLI:**
```bash
python -m evaluation.classification_eval
python -m evaluation.classification_eval --fail-under 0.92 --limit 2000
```

**Gate:** Macro F1 ≥ `--fail-under` (default 0.90; recommended 0.92 for demo).

**Output:** Rich table per category + `data/processed/confusion_matrix.png`.

---

## 2. `evaluation/rag_eval.py` (Existing)

Leave-one-out evaluation of the hybrid retriever: for each KB entry, use its text as a query and check whether the retriever returns that same entry in the top-k results.

**CLI:**
```bash
python -m evaluation.rag_eval
python -m evaluation.rag_eval --top-k 5 --fail-under-precision 0.80 --fail-under-mrr 0.70
```

**Metrics:** Precision@k, Recall@k (identical for LOO), MRR.

**Gate:** All three metrics must meet their thresholds.

---

## 3. `evaluation/llm_judge.py` (New)

Reads `llm_quality_score` values already stored in the `Resolution` table by the `EvaluatorAgent`. Scores are on a 0–5 scale (mean of relevance, completeness, actionability).

**CLI:**
```bash
python -m evaluation.llm_judge
python -m evaluation.llm_judge --fail-under 3.5 --limit 2000
```

**Output:**
- Summary statistics: mean, median, std, % above threshold
- Bucketed distribution table (five ranges from 0–5)
- Mean score per routing decision (auto_resolved / assigned / escalated)

**Gate:** `mean_score ≥ --fail-under` (default 3.5).

**Key implementation note:** Uses `ResolutionRepository.get_all_with_quality_scores()` (added to `resolution_repo.py`) which selects only rows where `llm_quality_score IS NOT NULL`.

---

## 4. `evaluation/end_to_end_eval.py` (New)

Loads all terminal-status tickets (AUTO_RESOLVED, ASSIGNED, ESCALATED, CLOSED) and computes latency from `created_at` to `updated_at` plus routing distribution.

**CLI:**
```bash
python -m evaluation.end_to_end_eval
python -m evaluation.end_to_end_eval --fail-latency 5.0 --fail-auto-resolve 25.0 --limit 2000
```

**Output:**
- Latency table: p50 / p95 / p99 in seconds
- Routing distribution: count + % per decision
- Auto-resolve rate (highlighted vs target)
- Category × routing matrix
- Confidence level distribution
- Multi-domain rate, repeated issue rate

**Gates (both must pass):**
- p95 latency ≤ `--fail-latency` (default 5.0 s)
- auto-resolve rate ≥ `--fail-auto-resolve` (default 25.0 %)

---

## 5. `evaluation/run_all.py` (New)

Unified entry point that calls all four evaluators in sequence and prints a final pass/fail summary table. A single `init_db()` is shared; each module runner is a lightweight async wrapper that captures the key metric.

**CLI:**
```bash
python -m evaluation.run_all

# With custom thresholds
python -m evaluation.run_all \
  --fail-under-f1 0.92 \
  --fail-under-precision 0.80 \
  --fail-under-mrr 0.70 \
  --fail-under-llm 3.5 \
  --fail-latency 5.0 \
  --fail-auto-resolve 25.0
```

**Final summary table columns:** Module | Status | Key Metric | Achieved | Target

**Exit code:** 0 if all pass, 1 if any fail.

---

## 6. `src/db/repositories/resolution_repo.py` Change

Added one method to `ResolutionRepository`:

```python
async def get_all_with_quality_scores(self, limit: int = 5000) -> list[Resolution]:
    """Return all Resolution rows where llm_quality_score is not NULL."""
    result = await self.session.execute(
        select(Resolution)
        .where(Resolution.llm_quality_score.is_not(None))
        .limit(limit)
    )
    return list(result.scalars().all())
```

---

## 7. Styling Conventions Followed

All new evaluators match the `classification_eval.py` pattern:
- `typer.Typer()` CLI with `typer.Option()` parameters
- `rich.console.Console()` + `rich.table.Table` for output
- `asyncio.run(_evaluate(...))` as the entry point
- `async with AsyncSessionLocal() as session:` for DB (not `get_async_session()`)
- `@dataclass` result structs
- `sys.exit(1)` on gate failure

---

## 8. Verification

### Prerequisites

```bash
cd backend

# 1. Generate and load synthetic training data
mamba run -n ticket_routing python -m scripts.generate_synthetic_data \
  --mode train --count 1200 --output data/raw/synthetic_train.csv
mamba run -n ticket_routing python -m scripts.load_tickets \
  --input-path data/raw/synthetic_train.csv --source synthetic_train

# 2. Train the classifier
mamba run -n ticket_routing python -m scripts.train_classifier

# 3. Process some tickets through the full pipeline (requires running API)
# Submit tickets via POST /api/v1/tickets/ingest — the background orchestrator
# populates classifications, resolutions, and quality scores
```

### Run individual evaluators

```bash
mamba run -n ticket_routing python -m evaluation.classification_eval --fail-under 0.92
mamba run -n ticket_routing python -m evaluation.rag_eval --top-k 5 --fail-under-precision 0.80
mamba run -n ticket_routing python -m evaluation.llm_judge --fail-under 3.5
mamba run -n ticket_routing python -m evaluation.end_to_end_eval --fail-latency 5.0 --fail-auto-resolve 25.0
```

### Run full suite

```bash
mamba run -n ticket_routing python -m evaluation.run_all
# Exit code 0 = all targets met
```

### Syntax / import smoke-test (no DB required)

```bash
DATABASE_URL="postgresql+asyncpg://test:test@localhost/test" \
SECRET_KEY="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
mamba run -n ticket_routing python -c "
import evaluation.llm_judge
import evaluation.end_to_end_eval
import evaluation.run_all
print('All imports OK')
"
```
