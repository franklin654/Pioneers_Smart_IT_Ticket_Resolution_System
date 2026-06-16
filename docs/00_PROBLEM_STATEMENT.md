# Problem Statement

## NASSCOM Hackathon — Trail Blazers

IT service companies receive thousands of support tickets daily, suffering from:

- Misrouted tickets
- Slow resolution
- Poor categorization
- Manual triaging

This system automates the full lifecycle:

**ingest → classify → retrieve similar resolutions → generate fix → route or escalate**

— with tracked confidence scores at every decision point, and a human in the loop
wherever automation cannot confidently make the call.

This statement, and the target metrics below, are unchanged from the original
hackathon brief. Everything else in this `docs/` set is the v2 design — informed by
what we learned building, testing, and UAT-ing v1 (see [`01_LESSONS_LEARNED.md`](01_LESSONS_LEARNED.md)).

## Target Metrics

| Metric | Target |
|---|---|
| Classification F1 | ≥ 0.92 |
| RAG Precision@5 | ≥ 80% |
| LLM Quality Score | ≥ 3.5 / 5.0 |
| Auto-Resolve Rate | ≥ 25% |
| E2E Latency p95 | < 5s |

These gates are enforced by the evaluation suite (see
[`06_DATA_AND_EVALUATION.md`](06_DATA_AND_EVALUATION.md)) — a build that doesn't clear
them is not done, regardless of how the architecture underneath evolves.

## Document Map

| File | Covers |
|---|---|
| `00_PROBLEM_STATEMENT.md` | This file — unchanged brief + target metrics |
| `01_LESSONS_LEARNED.md` | What v1 taught us; what we're keeping, changing, and why |
| `02_ARCHITECTURE.md` | v2 system architecture, pipeline diagram, tech stack |
| `03_BACKEND_DESIGN.md` | Domain structure, DB schema, routing engine, pipeline stages, auth |
| `04_FRONTEND_DESIGN.md` | React/Vite architecture, feature structure, UI flows |
| `05_API_CONTRACT.md` | Full endpoint contract, request/response shapes |
| `06_DATA_AND_EVALUATION.md` | Synthetic data pipeline, training, evaluation suite |
| `07_IMPLEMENTATION_PHASES.md` | Phased build order with verification gates per phase |
