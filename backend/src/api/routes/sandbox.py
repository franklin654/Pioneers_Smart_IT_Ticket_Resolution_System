"""Agent Sandbox — runs the full pipeline on ad-hoc text, returns per-agent traces.

No ticket is created or persisted. The pre-generation confidence gate is
intentionally bypassed: its outcome is surfaced as info in the classifier
trace so users can see what all stages would produce regardless of confidence.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from src.api.envelope import ok
from src.api.middleware.auth import CurrentUser
from src.api.middleware.rate_limiter import rate_limit
from src.agents.evaluator_agent import EvaluatorAgent
from src.classification.classifier import build_classifier
from src.core.config import get_settings
from src.db.database import session_scope
from src.db.models import TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator
from src.rag.generator import build_generator
from src.rag.reranker import MMRReranker
from src.routing.router import TicketRouter

router = APIRouter(
    prefix="/sandbox",
    tags=["sandbox"],
    dependencies=[Depends(rate_limit)],
)

_embedding_generator = EmbeddingGenerator()


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    category: TicketCategory | None = None


def _trace(
    agent: str,
    input_: str,
    output: str,
    latency_ms: int,
    error: str | None = None,
) -> dict:
    return {
        "agent": agent,
        "input": input_,
        "output": output,
        "latency_ms": latency_ms,
        "error": error,
    }


@router.post("/run")
async def run_sandbox(body: SandboxRequest, _: CurrentUser) -> dict:
    settings = get_settings()
    traces: list[dict] = []

    # Derive a synthetic title from the first sentence of the description
    first_sentence = body.description.split(".")[0].strip()
    title = first_sentence[:120] if first_sentence else "Sandbox ticket"

    # ── 1. Classify ───────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        classifier = build_classifier(Path(settings.model_dir) / "classifier.pkl")
        cls = await classifier.classify(title, body.description)
        category = body.category or cls.category
        latency = int((time.monotonic() - t0) * 1000)

        # Surface gate outcome as info without enforcing it
        router_check = TicketRouter().pre_generation_check(cls)
        gate_line = (
            f"gate: WOULD HALT → {router_check.decision.value} ({router_check.reason})"
            if router_check
            else "gate: pass"
        )

        traces.append(_trace(
            agent="ClassifierAgent",
            input_=f"title: {title}\ndescription: {body.description}",
            output=(
                f"category: {cls.category.value}\n"
                f"confidence: {cls.confidence:.2f} ({cls.confidence_level})\n"
                f"method: {cls.classification_method}\n"
                f"multi_domain: {cls.is_multi_domain}\n"
                f"{gate_line}"
            ),
            latency_ms=latency,
        ))
    except Exception as exc:
        traces.append(_trace(
            "ClassifierAgent", body.description, "",
            int((time.monotonic() - t0) * 1000), str(exc),
        ))
        return ok({"ticket_id": "sandbox", "traces": traces, "final_status": "error"})

    # ── 2. Retrieve (dense only — avoids BM25 full-table rebuild per request) ─
    retrieved = []
    t0 = time.monotonic()
    try:
        query_vector = await _embedding_generator.encode_one(f"{title} {body.description}")
        async with session_scope() as session:
            kb_repo = KnowledgeBaseRepository(session)
            raw = await kb_repo.search_similar(
                query_vector=query_vector,
                top_k=settings.rag_top_k,
                category_filter=category,
            )
        retrieved = [entry for entry, _ in raw]
        latency = int((time.monotonic() - t0) * 1000)
        traces.append(_trace(
            agent="RAGAgent (retrieval)",
            input_=(
                f"query: {title} {body.description[:100]}…\n"
                f"category_filter: {category.value}"
            ),
            output=(
                f"Retrieved {len(retrieved)} entries (dense/pgvector):\n" +
                "\n".join(f"{i+1}. [{e.category.value}] {e.title}" for i, e in enumerate(retrieved))
            ),
            latency_ms=latency,
        ))
    except Exception as exc:
        traces.append(_trace(
            "RAGAgent (retrieval)", "", "",
            int((time.monotonic() - t0) * 1000), str(exc),
        ))
        return ok({"ticket_id": "sandbox", "traces": traces, "final_status": "error"})

    # ── 3. Rerank (MMR diversity filter) ──────────────────────────────────────
    context = retrieved
    t0 = time.monotonic()
    try:
        reranker = MMRReranker(_embedding_generator)
        context = await reranker.rerank(f"{title} {body.description}", retrieved)
        latency = int((time.monotonic() - t0) * 1000)
        traces.append(_trace(
            agent="MMRReranker",
            input_=f"{len(retrieved)} candidates",
            output=(
                f"{len(context)} entries after MMR diversity filter:\n" +
                "\n".join(f"{i+1}. {e.title}" for i, e in enumerate(context))
            ),
            latency_ms=latency,
        ))
    except Exception as exc:
        traces.append(_trace(
            "MMRReranker", "", "",
            int((time.monotonic() - t0) * 1000), str(exc),
        ))
        # Non-fatal — continue with un-reranked candidates

    # ── 4. Generate ───────────────────────────────────────────────────────────
    steps = []
    t0 = time.monotonic()
    try:
        llm = build_generator()
        steps = await llm.generate(title, body.description, category, context)
        latency = int((time.monotonic() - t0) * 1000)
        traces.append(_trace(
            agent="LLMGenerator",
            input_=(
                f"title: {title}\n"
                f"category: {category.value}\n"
                f"context_entries: {len(context)}"
            ),
            output="\n".join(f"{s.step_number}. {s.instruction}" for s in steps) or "(no steps generated)",
            latency_ms=latency,
        ))
    except Exception as exc:
        traces.append(_trace(
            "LLMGenerator", "", "",
            int((time.monotonic() - t0) * 1000), str(exc),
        ))
        return ok({"ticket_id": "sandbox", "traces": traces, "final_status": "error"})

    # ── 5. Evaluate ───────────────────────────────────────────────────────────
    score = None
    t0 = time.monotonic()
    try:
        evaluator = EvaluatorAgent(build_generator())
        score = await evaluator._evaluate(title, body.description, category, steps, context)
        latency = int((time.monotonic() - t0) * 1000)
        would_route = (
            "auto_resolved" if score >= settings.llm_quality_threshold else "escalated"
        )
        traces.append(_trace(
            agent="EvaluatorAgent",
            input_=f"{len(steps)} steps to evaluate against {len(context)} KB entries",
            output=(
                f"quality_score: {score:.1f} / 5.0\n"
                f"threshold: {settings.llm_quality_threshold}\n"
                f"routing: {would_route}"
            ),
            latency_ms=latency,
        ))
    except Exception as exc:
        traces.append(_trace(
            "EvaluatorAgent", "", "",
            int((time.monotonic() - t0) * 1000), str(exc),
        ))

    final_status = (
        "auto_resolved"
        if score is None or score >= settings.llm_quality_threshold
        else "escalated"
    )

    return ok({"ticket_id": "sandbox", "traces": traces, "final_status": final_status})
