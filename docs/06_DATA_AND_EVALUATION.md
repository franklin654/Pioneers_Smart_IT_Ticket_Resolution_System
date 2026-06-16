# Data & Evaluation (v2)

## Data Sourcing — synthetic, canonical from day one

v1 started from a planned Kaggle CSV dataset, then replaced it mid-build with a
fully synthetic, Claude-generated corpus once the Kaggle data proved too thin/messy
for the 6-category split (see [`01_LESSONS_LEARNED.md`](01_LESSONS_LEARNED.md)).
v2 documents synthetic generation as the canonical source from the start — no
Kaggle/UCI loader code is written at all.

- `scripts/generate_synthetic_data.py` — Claude API generates labeled
  `{title, description, category}` rows across all 6 categories, with a deliberate
  mix of clear-cut and ambiguous/multi-domain-flavored tickets so the classifier's
  confidence distribution (and therefore the `AWAITING_REVIEW` path) gets exercised
  in evaluation, not just in production.
- `scripts/load_tickets.py` — loads the generated CSVs into `tickets`
  (`source = CSV`, training) and a held-out set (`source = WEBHOOK`) reserved for
  the routing-accuracy and holdout evaluators — never used in training, so accuracy
  numbers aren't inflated by leakage.

## Classifier Training

- `embedding/generator.py` — sentence-transformers `all-MiniLM-L6-v2`, target <50ms
  per ticket.
- `classification/trainer.py` — `LinearSVC` + `CalibratedClassifierCV` (for
  `predict_proba`), trained exclusively through `TicketRepository.get_training_data()`
  (audit fix H3 — see [`03_BACKEND_DESIGN.md`](03_BACKEND_DESIGN.md)).
- `classification/confidence.py` — maps top-1 probability to HIGH/MEDIUM/LOW bands
  and detects multi-domain ambiguity from the top-2 probability gap. Thresholds are
  settings-driven (`confidence_high_threshold`, `confidence_low_threshold`,
  `multi_domain_diff_threshold`), not hardcoded.

**Deferred, not blocking MVP:** a larger embedding model or an LLM-assisted
second-opinion classifier for borderline cases (UAT finding INT-11). The
pre-generation gate means a low-confidence ticket now gets routed to a correct
outcome (human reclassification) instead of a wrong one (bad auto-resolution), which
addresses the practical harm without requiring a model upgrade up front.

## Evaluation Suite

Six evaluators, all gating CI — a build that doesn't clear these isn't done:

| Evaluator | Metric | Gate |
|---|---|---|
| `classification_eval.py` | F1 (macro), accuracy, confusion matrix | F1 ≥ 0.92 |
| `rag_eval.py` | Precision@5, Recall@5, MRR | P@5 ≥ 0.80 |
| `llm_judge.py` | LLM-as-judge score distribution (Relevance + Completeness + Actionability) | Mean ≥ 3.5 / 5.0 |
| `end_to_end_eval.py` | Latency p50/p95/p99, routing decision distribution | p95 < 5s |
| `routing_accuracy_eval.py` | Agreement between `TicketRouter.decide()` output and a held-out labeled routing set | Tracked, not yet gated — informs threshold tuning |
| `holdout_eval.py` | Full pipeline run against the `WEBHOOK`-sourced held-out set, end to end | Tracked alongside the above; catches train/eval skew |

`routing_accuracy_eval.py` and `holdout_eval.py` were added organically during v1
(not in the original 4-evaluator plan) and are formalized here as permanent members
of the suite, not an undocumented add-on.

### New: pre-generation gate coverage

Because the gate (see [`02_ARCHITECTURE.md`](02_ARCHITECTURE.md)) means some tickets
never reach RAG/generation, `end_to_end_eval.py` reports the `AWAITING_REVIEW` rate
as its own bucket alongside `auto_resolved`/`assigned`/`escalated`, so it's visible
whether the gate is firing too often (classifier needs retraining) or rarely enough
to be a non-issue.
