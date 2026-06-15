# TicketIQ — UI Operations Guide (Ticket Resolution Console)

This document explains the **TicketIQ** web console end to end: what it is, how it
is wired to the backend, how to start it, how to operate it from a blank screen
through to a closed ticket, and exactly what each of the five tabs does.

It is written for operators (people triaging tickets) and for developers
(people running or extending the system).

---

## 1. What TicketIQ is

TicketIQ is the operator-facing console for the **Smart IT Ticket Resolution
System**. You paste in an IT incident (symptoms, logs, error text); a chain of AI
agents classifies it, retrieves similar past resolutions from a knowledge base,
drafts a step-by-step runbook, has an independent "LLM-as-Judge" score the draft,
and then routes the ticket to one of three outcomes:

| Outcome | Meaning |
|---|---|
| **Auto-Resolved** | High-confidence, high-quality fix — safe to apply directly. |
| **Assigned** | Routed to an L1/L2 team with a suggested runbook to action. |
| **Escalated** | Low confidence / low quality / repeated issue — sent to a specialist. |

You stay in the loop: you review the AI's runbook and **accept**, **edit**, or
**reject** it. Your decision is recorded as feedback.

---

## 2. How the UI is wired (architecture)

There are three layers. **You only ever open the middle one in your browser.**

```
┌─────────────────────────┐     ┌──────────────────────────┐     ┌────────────────────────┐
│  React UI (the browser) │ ──▶ │  Express BFF (server.ts)  │ ──▶ │  FastAPI backend       │
│  src/ — the design      │     │  + backendBridge.ts       │     │  (Python, Postgres,    │
│  you see and click      │ ◀── │  http://localhost:3000    │ ◀── │  pgvector, Ollama LLM) │
└─────────────────────────┘     └──────────────────────────┘     │  http://localhost:8000 │
                                                                  └────────────────────────┘
```

- **React UI (`src/`)** — the visual design. It only talks to the BFF at
  `/api/v1/...`. It never talks to the Python backend directly.
- **BFF / bridge (`server.ts` + `backendBridge.ts`)** — a thin Express server that
  serves the UI *and* proxies every request to the FastAPI backend, translating
  the backend's data into the richer shape the UI expects.
- **FastAPI backend (`../backend`)** — the real engine: agents, classifier, RAG,
  evaluator, router, and the Postgres + pgvector database.

### Two run modes
The BFF runs in one of two modes, decided by `BACKEND_API_URL` in `frontend/.env`:

- **Backend mode** (`BACKEND_API_URL` set) — the real system. Every ticket is
  processed by the Python agents against the real database. **This is the mode
  this guide assumes.**
- **Simulation mode** (`BACKEND_API_URL` unset) — a self-contained demo engine
  inside the BFF (no Python backend needed). Useful for UI-only demos.

`GET /api/v1/system` reports which mode is active (`"backend"` or `"simulation"`).

---

## 3. Starting the system (from nothing to a running console)

### Prerequisites
- Node.js 20+
- Python 3.12+ with the project venv (`../venv`)
- PostgreSQL with the `pgvector` extension, database `ticket_routing`, loaded with
  ticket + knowledge-base data
- An LLM for resolution generation — **Ollama** running locally (model
  `gemma4:latest`) *or* an `ANTHROPIC_API_KEY` configured in `backend/.env`

### Step 1 — start the backend (FastAPI)
```bash
cd backend
../venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```
Backend is up when `http://localhost:8000/docs` returns the Swagger page.

> **Important for local (non-Docker) runs:** in `backend/.env` set
> `OLLAMA_BASE_URL=http://localhost:11434`. The committed default
> `http://ollama:11434` is a Docker-network hostname and is unreachable when you
> run outside Docker — if it's wrong, every ticket silently **escalates** instead
> of generating a resolution.

### Step 2 — start the UI / BFF
```bash
cd frontend
npm install            # first time only

# Production (recommended — no file-watcher, robust):
npm run build
npm start              # serves on http://localhost:3000

# …or development with hot reload:
npm run dev            # also http://localhost:3000
```

Confirm `frontend/.env` has:
```
BACKEND_API_URL=http://localhost:8000
BACKEND_ADMIN_USERNAME=admin
BACKEND_ADMIN_PASSWORD=<must match backend/.env ADMIN_PASSWORD>
```

### Step 3 — open the console
Open **http://localhost:3000**. The UI auto-authenticates with the demo operator
credentials **`admin` / `changeme123`** (these log you into the BFF; the BFF
separately authenticates to FastAPI using the `BACKEND_ADMIN_*` service creds).

You should land on the **Incident Ingest Desk** tab with the top nav showing the
system status as online.

---

## 4. What happens when you submit a ticket (the pipeline)

When you click **"Commit & Run Resolution Pipeline"**, the ticket is created
(HTTP `202 Accepted`) and queued for asynchronous processing. The UI switches to
the **Triage & Resolution Board** and shows the pipeline advancing through these
stages **in real time** (a live stepper: Intake → Classify → Retrieve → Generate →
Judge):

| Stage (ticket status) | Agent | What it does |
|---|---|---|
| `new` | IntakeAgent | Ticket persisted; PII detected and masked. |
| `classifying` / `classified` | ClassifierAgent | Predicts category + confidence. |
| `retrieving` | RAGAgent (retriever) | Hybrid search over the KB for similar tickets. |
| `generating` | RAGAgent (generator) | LLM drafts the step-by-step runbook. |
| `evaluating` | EvaluatorAgent | LLM-as-Judge scores relevance/completeness/actionability. |
| `auto_resolved` / `assigned` / `escalated` | TicketRouter | Final routing decision. |

The console receives these transitions over a WebSocket (`/ws/tickets/:id`, with a
REST polling fallback) and refreshes the view as each stage completes.

> **Note on timing:** the local LLM (`gemma4` via Ollama) is not instant — a full
> run typically takes **~45–70 seconds** (generation ~30–40s, judging ~15–20s).
> The stepper animating through Classify → Generate → Judge is your signal that it
> is working. If it sits on `new` and never advances, the LLM is unreachable — see
> Troubleshooting.

---

## 5. The five tabs

### 5.1 Incident Ingest Desk (`intake`)
**Where you report a new incident and launch the pipeline.**

- **Incident Summary Title** — short title (required).
- **Priority Level** — Low / Medium / High / Critical (mapped to backend priority 1–4).
- **Target System Domain** — leave on *"AI Automated Classification Core"* to let
  the classifier decide, or force a category (Infrastructure, Application, Security,
  Database, Access Management, Network).
- **Auto-Resolution Confidence Threshold** — a slider; tickets classified below this
  confidence are biased toward escalation rather than auto-resolution.
- **Raw Symptoms Payload** — the description / logs / error text (required).
- **Scenario Templates** (right panel) — one-click presets (SQL Timeout, Brute
  Force, Node Eviction) that fill the form so you can try the system instantly.
- **Privacy Shield** (right panel) — explains that PII (emails, IPs, secrets) is
  detected and masked before anything is stored.
- **Commit & Run Resolution Pipeline** — submits the ticket and starts processing.

### 5.2 Triage & Resolution Board (`resolution`)
**The main working surface — where the AI's runbook appears and you action it.**

- A **ticket list** (left) to switch between tickets; the active ticket's full
  detail shows on the right.
- The **live stage stepper** while processing (Intake → Classify → Retrieve →
  Generate → Judge).
- **Classification** — predicted category and confidence.
- **Resolution runbook** — the AI's numbered, step-by-step fix, each step copyable.
- **EvaluatorAgent (LLM-as-Judge) scores** — Relevance / Completeness /
  Actionability and an average grade out of 5, plus a rationale.
- **Knowledge sources** — the similar past tickets the runbook was grounded in.
- **Routing banner** — Auto-Resolved / Assigned / Escalated (with the assigned
  team or escalation reason).
- **Human-in-the-loop actions** — you can:
  - **Accept** the runbook as-is,
  - **Edit** the steps in the checkout editor and commit the modified version, or
  - **Reject** it.
  Add your **operator signature (name)** and click **Commit & Approve** to close the
  ticket and index the accepted resolution back into the Knowledge Base.
- **Translate** — render the runbook in another language for the end user.

### 5.3 AI Reasoning Logs & Sandbox (`reasoning`)
**A transparent, terminal-style transcript of the agents' reasoning for the active
ticket.** Each agent (IntakeAgent → ClassifierAgent → RAGResolverAgent →
EvaluatorAgent) logs what it did and why, so you can audit *how* the resolution was
reached, not just the final answer. You can export the triage log as JSON for the
ticket record.

### 5.4 Evergreen KB Runbooks (`faq`)
**A searchable browser over the real knowledge base** (`knowledge_base_entries` —
~1,200 resolved-ticket runbooks). Search by keyword and filter by category; each
entry shows its title, category, description, and the resolution steps. This is the
same corpus the RAG stage retrieves from, so it's both a reference library and a
window into what the AI is grounding its answers on. Accepted resolutions from the
Triage board are indexed here, so the KB grows over time.

### 5.5 Telemetry & Health Metrics (`analytics`)
**The operations dashboard — live aggregates computed from the real database.**

- **KPI cards** — Total Audited (tickets processed), AI Auto-Resolve %, Allocated
  L1/L2 %, L2 Escalations %, and the average Judge Score.
- **30-day incident & resolution timeline.**
- **Breakdowns** — tickets by category, by priority, by routing outcome, by status.

These figures update as new tickets flow through the pipeline (ingest a ticket and
the Total Audited count and distributions move).

---

## 6. End-to-end operator workflow (start to finish)

1. Open **http://localhost:3000** (auto-login as `admin`).
2. On **Incident Ingest Desk**, enter a title + description (or click a Scenario
   Template), set priority, optionally pick a category, then click **Commit & Run
   Resolution Pipeline**.
3. You're taken to the **Triage & Resolution Board**. Watch the stepper run through
   Classify → Generate → Judge (~1 minute on the local LLM).
4. When it finishes, review the **runbook**, the **Judge scores**, and the
   **knowledge sources**. Open **AI Reasoning Logs & Sandbox** if you want to audit
   the agents' reasoning.
5. Decide: **Accept**, **Edit & commit**, or **Reject**. Enter your operator name
   and **Commit & Approve** to close the ticket — the accepted runbook is indexed
   into the **Evergreen KB Runbooks**.
6. Check **Telemetry & Health Metrics** to see the updated counts and rates.

---

## 7. Ticket status / routing reference

| Status | Stepper | Meaning |
|---|---|---|
| `new` | Intake | Created; queued. |
| `classifying` / `classified` | Classify | Category being / has been predicted. |
| `retrieving` | Retrieve | Searching the KB. |
| `generating` | Generate | LLM drafting the runbook. |
| `evaluating` | Judge | LLM-as-Judge scoring the draft. |
| `auto_resolved` | done | High-quality fix, applied automatically. |
| `assigned` | done | Routed to an L1/L2 team. |
| `escalated` | done | Sent to a specialist (low confidence/quality or repeated issue). |
| `closed` / `resolved` | done | Operator approved and closed. |

---

## 8. Troubleshooting

- **The button "does nothing" / the ticket sits on `new` forever.**
  The ticket *was* created — the pipeline is waiting on the LLM. Almost always the
  LLM is unreachable: in `backend/.env` set `OLLAMA_BASE_URL=http://localhost:11434`
  (not the Docker hostname `ollama:11434`) and confirm Ollama is running with the
  `gemma4:latest` model (`curl http://localhost:11434/api/tags`). Alternatively set
  `LLM_BACKEND=claude` with a valid `ANTHROPIC_API_KEY`. Without a reachable LLM the
  backend escalates every ticket instead of generating a resolution.

- **It takes about a minute per ticket.** Expected with the local LLM. The live
  stepper (Classify → Generate → Judge) confirms it's running.

- **Analytics / KB look empty or wrong.** Confirm backend mode is active
  (`GET http://localhost:3000/api/v1/system` → `"mode":"backend"`) and that the
  database is loaded. In simulation mode these tabs show seeded demo data only.

- **Blank page / login fails.** Verify both servers are up (`:8000` and `:3000`) and
  that `BACKEND_ADMIN_PASSWORD` in `frontend/.env` matches `ADMIN_PASSWORD` in
  `backend/.env`.

- **WebGL warnings in some headless/remote setups.** The console uses animated
  WebGL canvases; on machines without a GPU you may need software rendering. Normal
  desktop browsers are unaffected.

---

## 9. Related docs
- `frontend/INTEGRATION.md` — exact endpoint-by-endpoint mapping between the UI, the
  BFF, and FastAPI, plus the schema adaptations.
- `frontend/UI_DOCUMENTATION.md` — component-level UI notes.
- `backend/README.md` — backend setup, data loading, and the agent pipeline.
- Root `README.md` — the integrated quick start.
