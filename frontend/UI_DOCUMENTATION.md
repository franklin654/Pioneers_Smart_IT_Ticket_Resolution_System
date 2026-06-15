# TicketIQ: Real-Time Incident Triage & Auto-Resolution Workspace - UI Specifications & Architecture

Welcome to the official user interface documentation for the **TicketIQ Workspace**. This document provides an in-depth breakdown of the visual components, custom charts, real-time feedback loops, and architectural integrations configured within this system.

---

## 🛠️ Visual System Architecture
The workspace is engineered with a high-contrast, space-age slate dark visual identity to mimic modern Security Operations Centers (SOCs) and cloud console environments. 

### Core Design Systems
*   **Typography Pairing**: Space Grotesk (tech-forward display headers) paired with Inter (fluid sans-serif workspace readability) and JetBrains Mono (low-level telemetry diagnostics and system parameters).
*   **Theme Profile (Cosmic Slate Dark)**: Built entirely upon high-density translucent glass containers (Tailwind class-augmented glassmorphism with delicate border outlines `border-white/5` and `bg-black/35`).
*   **Intelligent Animation Suite**: Embedded `motion` micro-transitions (imported from `motion/react`) for active ticket selectors, fade-in route switches, dynamic threshold alterations, and rotating coordinate tracers.

---

## 🎚️ Feature Blueprint & Interface Highlights

### 1. Active Incident Triage Queue & Quick Search
*   **Real-time Signal Streaming**: Visualized via an active telemetry signals column grouping tickets chronologically (unshifted to top). Clicking triggers instantaneous viewport adjustments.
*   **JSON Audit Logger**: Included a dedicated **Export Log** command allowing SOC supervisors to download fully structured ticket collections along with complete runbook evaluations in valid JSON metadata files.
*   **Telemetry Search Filter**: A live quick-filter box lets operators isolate signal configurations instantly utilizing partial matches on title strings, unique UUIDs, or short identifiers.

### 2. Router Intelligence Scorecard
Designed with a clean multi-model semantic classifier telemetry analyzer:
*   **Confidence Distribution Card**: Displays a fine-tuned horizontal bar chart array showing probability percentages across all six standard domains (Infrastructure, Application, Security, Database, Access Management, Network).
*   **Tier-2 Escalation Alert Block**: Triggers a dynamic warning banner with amber warning symbols and detailed textual rationale explanation whenever routing bypass mechanics direct an incident out of standard automation pipelines.

### 3. Progressive Resolution Scoreboard (Doughnut System)
Located directly inside the **Resolution** panel, this customized component computes live metrics matching input variables:
*   **Target Limit Indicator Segment**: Embeds a visual pink target line representing the dynamic **Min Confidence Threshold** slider setting.
*   **Doughnut Gauge Overlay**: A smooth SVG stroke transition illustrating the classification score. It automatically adapts color values based on state logic:
    *   **Emerald Theme (`#22d3ee`)**: Activated when the overall classification score successfully breaches the target minimum limit.
    *   **Rose Theme (`#f43f5e`)**: Auto-enabled when the engine falls short of target limits, displaying explicit warnings informing why the incident was safely escalated.

---

## 🧭 File and Component Structure

*   `server.ts`: Full-stack backend controller running robust text processing, RAG (Retrieval-Augmented Generation) emulation, PII masking, and multi-model classification pipelines with Gemini-3.5-Flash integration and local heuristic fallbacks.
*   `src/App.tsx`: Parent UI coordinator, managing local triage states, active ticket tracking, JWT authentication configurations, and live coordinate charts.
*   `src/components/ResolutionTab.tsx`: Primary visual engine representing active remediation steps, integrated translation engines, user feedback loops, and the new SVG Doughnut Gauge Scoreboard.

---

## 🧠 Diagnostic Pipelines & Multi-Model Engine
The server's classification agent now runs an intelligent Gemini-3.5-flash processing layer with comprehensive fallback mechanisms:
1.  **Direct API Routing Layer**: Translates incoming service tickets to structured JSON payloads classifying the accurate IT category while computing specific confidence weights.
2.  **Robust Native Heuristics fallback**: In cases of strict rate limit triggers, API offline events, or authorization mismatches, an algorithmic search arrays keywords against extensive term lists, seamlessly delivering high-fidelity confidence weights.
