# TicketIQ IT Desk - Pipeline Architecture Documentation

Welcome to the **TicketIQ Autonomous Core** architecture blueprint. This manifest maps out the sequential pipeline execution flow, data definitions, and component file responsibilities spanning from ticket ingestion to supervised human-in-the-loop closure.

---

## 🛠️ File Structure & Responsibilities

The application follows a full-stack design using **Vite + React (TypeScript)** on the client side and **Node.js (Express + TypeScript)** on the server.

```
/
├── server.ts                       # Full-Stack Express Server (Main Entrypoint)
│                                    - Simulates synchronous Multi-Agent Stepper Pipeline with delays
│                                    - Uses Google Gemini API (if available) for classification & synthesis
│                                    - Controls persistent state, telemetry analytics logs & system seeds
├── metadata.json                   # Applet Capabilities Config (Name, Description, and Gemini API permissions)
├── package.json                    # Npm Dependencies & bundler configurations (tsx, esbuild, vite)
│
└── src/
    ├── main.tsx                    # React bootstrapping standard entry point
    ├── App.tsx                     # Core Client UI Dashboard
    │                                - Houses Input Console, Queue managers, Terminal Log Stream & operator checks
    ├── types.ts                    # Declares shared TypeScript model structures
    └── components/
        ├── CoreParticleCanvas.tsx  # Interactive WebGL Theme Visualizer (built with Three.js)
        │                            - Dynamically re-aligns particle coordinates based on active agent status
        └── WeatherCanvas.tsx       # Backup canvas wrapper for general visual effects
```

---

## 🚀 The 9-Stage Orchestration Pipeline Flow

The core system models an autonomous multi-agent hierarchy processing raw ticket symptoms. Each phase can translate coordinates in the 3D WebGL particle space, changing shape state with real-time feedback.

```
[1. Intake] ──> [2. Scrub (PII MASK)] ──> [3. Classify (Softmax)] ──> [4. Match (RAG Runbooks)]
                                                                                │
                                                                                v
[8. Approved/Modified KB] <── [7. Decisions Gate] <── [6. LLM-as-Judge] <── [5. Synthesize Runbook]
```

### 📋 Phase-by-Phase Detail:

#### 1. Intake (`IntakeAgent`)
- **Action**: Catches the incident title, raw symptoms payload, priority (Low/Medium/High/Critical), and source channel.
- **Language Analysis**: Heuristically determines incoming languages (e.g., English, Spanish, French, Hindi) to handle global localized translation downstream.

#### 2. Scrub PII (`IntakeAgent` - Privacy Layer)
- **Action**: Runs high-speed regex engines over incoming raw text.
- **Outcome**: Automatically sanitizes sensitive customer/environment footprints:
  - Phone numbers are replaced with `[MASKED_PHONE]`
  - IP host addresses are replaced with `[MASKED_IP]`
  - Email addresses are replaced with `[MASKED_EMAIL]`

#### 3. Classification (`ClassifierAgent`)
- **Action**: Simulates structural category probability vector distributions (Softmax indices) across 6 focus domains: `Infrastructure`, `Application`, `Security`, `Database`, `Storage`, or `Network`.

#### 4. Retrieval & Similarity Search (`RAGResolverAgent`)
- **Action**: Executes semantic searches, parsing active category indexes inside the global Knowledge Base to match historical templates or identical incident profiles.

#### 5. Synthesis & Drafting (`RAGResolverAgent` + Gemini Core)
- **Action**: If a Gemini API key is configured, queries the model with structural system instructions to generate exactly 4-5 hyper-realistic command-line resolution checklists.
- **Fallback**: Extracts resolution blocks directly from the matching KB category runbook.

#### 6. Smart Evaluation Audit (`EvaluatorAgent` - Dual-Judge LLM-as-Judge)
- **Action**: Runs validation audits rating the drafted checklist from 1 to 5 across 3 standard metrics: **Relevance**, **Completeness**, and **Actionability**. Renders a natural language structural evaluation rationale.

#### 7. Routing Decisions Gateway (`RoutingManager`)
- **Action**: Tallies classification confidence ratings alongside LLM average judge weights to route the incident into one of 3 final destinations:
  - **Auto-Solve Gate**: High confidence (>85%) + Good Judge score (>=3.8) -> Bypasses queue for automated Operator Human review.
  - **Engineer Dispatch Queue**: Standard incident needing dedicated human verification or tier-1 operations team checklists.
  - **Critical Escalation L2**: Lower confidence (<60%) or Critical Priority incident flagged for instant senior engineering attention.

#### 8. Operator Human-in-the-Loop Review (`Staff Operator #09`)
- **Action**: Staff operator reviews synthesized draft. Inside the control center, the operator can:
  - **Approve Runbook**: Locks the resolution instantly, routing status to `closed`.
  - **Modify & Commit**: Edits individual runbook command lines manually and updates the ticket, immediately appending the corrected checklist to the public Knowledge Base index.
  - **Reject & Escalate**: Flags the runbook as invalid and reroutes coordinates to the manual Escalation queue.

---

## 📡 API Endpoints Index

All routes serve JSON structures over prefix `/api/v1/*`.

| Method | Endpoint | Description | Payload Schema | Response Schema |
| :--- | :--- | :--- | :--- | :--- |
| **GET** | `/api/v1/config` | Retrieves permitted category tags & options | *None* | `{ categories: string[], priorities: string[], sources: string[] }` |
| **GET** | `/api/v1/system` | Retrieves system status & LLM deployment status | *None* | `{ embedding_provider: string, llm_enabled: boolean, llm_model: string, knowledge_base: number }` |
| **GET** | `/api/v1/tickets` | Lists currently active & historical tracked tickets | *None* | `{ tickets: Ticket[] }` |
| **GET** | `/api/v1/tickets/:id` | Returns single ticket coordinates and agent telemetry log | *None* | `Ticket Object` |
| **POST** | `/api/v1/tickets/ingest` | Triggers raw ticket creation and async multi-agent loop | `{ title, description, priority, category, source }` | `Ticket Object (Status = "new")` |
| **POST** | `/api/v1/resolutions/:id/feedback` | Commits Operator HITL review feedback and updates global KB | `{ feedback_type: "accepted"\|"modified"\|"rejected", reviewed_by, modified_text }` | `{ knowledge_base_updated: boolean, ticket_status: string }` |
| **POST** | `/api/v1/tickets/:id/translate` | Triggers real-time LLM-driven translation of runbooks | *None* | `{ translation: { steps: string[] } }` |
| **GET** | `/api/v1/knowledge` | Queries or filters public KB procedurals | *Query params: `q` (string), `category` (string)* | `{ items: KBItem[] }` |
| **GET** | `/api/v1/analytics` | Returns 30-day historical outage counts | *None* | `Array<{ date: string, incidents: number, auto_resolved: number }>` |

---

## 💎 State Coordinate Matrix Map

For the Interactive ThreeJS WebGL view, individual particle structures map to state parameters:

| Ticket Status | 3D Space Target Shape representation | Rationale Description |
| :--- | :--- | :--- |
| `none` / `new` | **Concentric Sphere** | Stable initial baseline state. Particles rotate in locked spherical orbits. |
| `classifying` | **Decomposing Scattered Cloud** | Particles explode outwards as symptoms are parsed and PII is scrubbed. |
| `classified` / `retrieving` | **Linear Gravity Vortex** | Particles collapse into dense gravitational rings as KB RAG runs. |
| `generating` | **Logarithmic Galaxy Spiral** | Beautiful double-spiral galaxy representing active LLM drafting. |
| `evaluating` | **Orthogonal Hypercube Grid** | Strict block matrices representing parallel security & relevance filters. |
| `auto_resolved` / `closed` / `resolved` | **Crystalline Emerald Core** | Bright emerald dense core signifying successfully solved procedurals. |
| `assigned` | **Concurrently Arrayed Lines** | Particles align in pipeline grids reflecting downstream DevOps backlogs. |
| `escalated` | **Dual-Opposing Polar Shells** | Unbalanced red split shells reflecting active intervention flags. |
