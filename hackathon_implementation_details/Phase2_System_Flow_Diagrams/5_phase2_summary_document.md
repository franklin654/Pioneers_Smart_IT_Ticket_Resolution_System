# Phase 2: System Flow Diagrams - Summary Document
## AI Powered Intelligent Ticket Routing & Resolution Agent

**Version:** 2.0 - Design Focus  
**Date:** 2026  
**Classification:** Hackathon Round 2 Documentation

---

## Executive Summary

This document provides comprehensive explanations of all system flow diagrams created in Phase 2, focusing on **design specifications and flow logic** rather than implementation code.

**Revision Note:** This version removes all Python implementation code and focuses purely on design specifications, flow logic, and architectural decisions.

---

## 1. DATA FLOW DIAGRAM (DFD)

### 1.1 DFD Level 0 (Context Diagram)

**Purpose:** Show system boundaries and external entities

**External Entities:**
1. ITSM Systems (ServiceNow, Jira)
2. CSV Upload (Manual bulk import)
3. Support Agents (L1, L2, L3)
4. System Administrators

**Data Flows:**
- ITSM → System: Raw tickets (JSON webhooks)
- CSV → System: Batch tickets (file upload)
- System → Agents: Routed tickets + resolutions
- Agents → System: Feedback (accepted/rejected/modified)
- System → ITSM: Status updates (sync)

---

### 1.2 DFD Level 1 (Decomposed Processes)

**Processes:**

| ID | Process | Inputs | Outputs | Purpose |
|----|---------|--------|---------|---------|
| P1 | Ingest Tickets | Raw data | Validated tickets | Validate, mask PII, dedupe |
| P2 | Generate Embeddings | Text | 384-dim vectors | Semantic representation |
| P3 | Classify Tickets | Embeddings | Category + confidence | ML prediction |
| P4 | Retrieve Similar | Query vector | Top-5 similar | Hybrid search |
| P5 | Generate Resolution | Context | Resolution steps | LLM synthesis |
| P6 | Evaluate Resolution | Resolution | Quality scores | LLM-as-judge |
| P7 | Route Ticket | Classification + eval | Routing decision | Auto/assign/escalate |
| P8 | Update KB | Accepted solutions | Updated KB | Continuous learning |

**Data Stores:**
- D1: Tickets DB
- D2: Vector Store (pgvector)
- D3: Classifications
- D4: Resolutions
- D5: Knowledge Base
- D6: Routing History (audit)

---

## 2. SEQUENCE DIAGRAM

### 2.1 Component Interaction

**11 Components:**
1. ITSM System
2. API Gateway
3. Ingestion Service
4. Database
5. Embedding Service
6. Classifier
7. RAG Pipeline
8. LLM (Mistral-7B)
9. Evaluator
10. Routing Engine
11. UserProxy

### 2.2 Latency Budget

**Total Target:** < 5 seconds end-to-end

| Phase | Target | Description |
|-------|--------|-------------|
| Synchronous (API) | < 440ms | Validate, mask PII, store |
| Embedding | < 50ms | Generate 384-dim vector |
| Classification | < 100ms | Predict category |
| RAG Retrieval | < 500ms | Hybrid search |
| LLM Generation | < 3000ms | Mistral-7B inference |
| Evaluation | < 1000ms | LLM-as-judge |
| Routing | < 10ms | Business logic |
| **Total** | **< 5000ms** | **4700ms used, 300ms buffer** |

---

## 3. STATE TRANSITION DIAGRAM

### 3.1 State Specifications

**12 States:**
- NEW: Just ingested
- CLASSIFYING: Prediction in progress
- CLASSIFIED: Category assigned
- RETRIEVING: Fetching similar tickets
- GENERATING: LLM creating resolution
- EVALUATING: Quality scoring
- AUTO_RESOLVED: High confidence + approved
- ASSIGNED: Medium confidence → department
- ESCALATED: Low confidence → specialist
- IN_PROGRESS: Agent working
- RESOLVED: Solution provided
- CLOSED: Archived
- REOPENED: Issue recurred

### 3.2 Transition Guards

**Design Specifications (NOT implementation code):**

**G1: Confidence Threshold**
```
SPECIFICATION:
  IF confidence > 0.85: Can auto-resolve
  IF 0.60 ≤ confidence ≤ 0.85: Route to department
  IF confidence < 0.60: Escalate
```

**G2: Multi-Domain Detection**
```
SPECIFICATION:
  Calculate: difference = top1_probability - top2_probability
  IF difference < 0.15: Flag as multi-domain, escalate
  ELSE: Single domain, proceed normally
```

**G3: UserProxy Approval**
```
SPECIFICATION:
  For auto-resolve path:
    1. Present resolution to human
    2. Wait for explicit confirmation (max 1 hour)
    3. IF approved: Proceed to auto-resolved
    4. IF rejected: Route to assigned
    5. IF timeout: Escalate
```

**G4: LLM Quality Score**
```
SPECIFICATION:
  avg_score = (relevance + completeness + actionability) / 3
  IF avg_score ≥ 3.5: Quality acceptable
  ELSE: Route to human review
```

### 3.3 Transition Actions

**A1: Log Routing Decision**
- Create audit record in routing_history
- Fields: ticket_id, from_status, to_status, confidence, reason, timestamp
- Purpose: Compliance, debugging, analytics

**A2: Notify Agent**
- Retrieve agent contact info
- ASSIGNED: Normal email + Slack
- ESCALATED: Urgent email + SMS + PagerDuty (if P0/P1)

**A3: Update Knowledge Base**
- Accepted feedback: Add to KB, generate embedding, index
- Modified feedback: Replace with corrected version
- Rejected feedback: Mark invalid, exclude from retrieval

---

## 4. CRITICAL PATHS

### 4.1 Happy Path (Auto-Resolve) - 25-30% of tickets
```
NEW → CLASSIFYING → CLASSIFIED → RETRIEVING → GENERATING → 
EVALUATING → AUTO_RESOLVED → CLOSED

Requirements:
- Confidence > 0.85
- avg_score ≥ 3.5
- UserProxy approves

Time to close: ~15 minutes (5s processing + ~15 min human approval)
```

### 4.2 Department Route - 50-60% of tickets
```
NEW → ... → EVALUATING → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED

Requirements:
- 0.60 ≤ Confidence ≤ 0.85
- AI suggestion provided

Time to close: ~6 hours (5s processing + 4h agent pickup + 2h resolution)
```

### 4.3 Escalation Path - 15-20% of tickets
```
NEW → ... → EVALUATING → ESCALATED → IN_PROGRESS → RESOLVED → CLOSED

Requirements:
- Confidence < 0.60 OR is_multi_domain = true

Time to close: ~5 hours (5s processing + 1h specialist pickup + 4h resolution)
```

---

## 5. DESIGN DECISIONS

### 5.1 Why Three Routing Paths?

**Decision:** Auto-resolve / Department-route / Escalate

**Rationale:**
- Single path: No automation benefit
- Two paths: Doesn't differentiate medium vs low confidence
- Three paths: Optimal automation vs safety balance

**Expected Distribution:**
- 25-30% auto-resolved
- 50-60% department-routed with AI assistance
- 15-20% escalated to specialists

---

### 5.2 Why UserProxy for Auto-Resolve?

**Decision:** Require human confirmation before auto-closing

**Rationale:**
- Risk mitigation: AI resolution could be wrong
- Trust building: Human reviews before closure
- Gradual adoption: Remove after 90% accuracy proven

**Trade-offs:**
- ✅ Prevents wrong auto-closures
- ⚠️ Adds 15-minute latency

---

### 5.3 Why Asynchronous Processing?

**Decision:** API returns immediately, processing in background

**Rationale:**
- User experience: Fast response (< 440ms)
- Scalability: Non-blocking ingestion
- Throughput: Queue while processing

**Trade-offs:**
- ✅ Better UX, higher throughput
- ⚠️ Eventually consistent, needs WebSocket for updates

---

## 6. MONITORING STRATEGY

### 6.1 Metrics by Diagram Type

**DFD Metrics (Data Quality):**
- Ingestion rate: tickets/minute
- PII detection rate: % with entities found
- Duplicate rate: % flagged

**Sequence Metrics (Performance):**
- API response time: p50, p95, p99
- End-to-end latency: full pipeline timing
- Component latency: per-step breakdown

**State Metrics (Business KPIs):**
- Auto-resolve rate: % reaching AUTO_RESOLVED
- Escalation rate: % reaching ESCALATED
- Resolution time: NEW → RESOLVED duration
- Reopen rate: % transitioning CLOSED → REOPENED

---

## 7. ERROR HANDLING DESIGN

### 7.1 Synchronous Phase Errors

| Error | Response | Recovery |
|-------|----------|----------|
| Schema validation fails | 400 Bad Request | Caller fixes and retries |
| PII detection fails | Log warning, continue | Proceed without masking |
| Database write fails | 500 Internal Error | Retry with exponential backoff |
| Duplicate detected | 409 Conflict | Return existing ticket_id |

### 7.2 Asynchronous Phase Errors

| Error | Fallback Strategy | Final State |
|-------|-------------------|-------------|
| Embedding fails | Retry 3x, then escalate | ESCALATED |
| Classification timeout | Default "Unknown" | ESCALATED |
| RAG retrieval empty | LLM zero-shot (no context) | EVALUATING |
| LLM generation timeout | Template resolution | ASSIGNED |
| Evaluator fails | Assume score=3.0 | Continue with caution |

---

## CONCLUSION

This Phase 2 summary provides:
- ✅ Complete diagram explanations
- ✅ Flow specifications and design logic
- ✅ Performance targets and critical paths
- ✅ Design decisions with clear rationale
- ✅ Monitoring and error handling strategies

**No implementation code** - pure design specifications.

---

**Document Prepared By:** Trail Blazers Team  
**Last Updated:** 2026  
**Status:** Design-focused, implementation-independent
