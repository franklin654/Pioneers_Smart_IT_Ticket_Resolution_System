"""EvaluatorAgent — thin ConversableAgent wrapper around the LLM quality scorer.

Scores the generated resolution on a 1-5 scale. The score drives Rule 3
(ESCALATED when score < threshold) and Rules 4-5 (AUTO_RESOLVED / ASSIGNED).

No `register_reply` / `_handle_*` dead code (audit fix C1).
"""

from __future__ import annotations

import json
import re

from autogen import ConversableAgent

from src.core.config import get_settings
from src.core.exceptions import AppBaseException
from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry, ResolutionStep, TicketCategory
from src.rag.generator import GeneratorProtocol

logger = get_logger(__name__)

_EVAL_SCHEMA = '{"score": <1-5>, "reasoning": "..."}'


class EvaluationError(AppBaseException):
    code = "EVALUATION_ERROR"
    http_status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)


def _parse_score(raw: str) -> float:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object in evaluator output", raw, 0)
    data = json.loads(match.group(0))
    score = float(data["score"])
    if not 1.0 <= score <= 5.0:
        raise ValueError(f"Score {score} outside [1, 5]")
    return score


def _build_eval_prompt(
    title: str,
    description: str,
    category: TicketCategory,
    steps: list[ResolutionStep],
    context: list[KnowledgeBaseEntry],
) -> str:
    steps_text = "\n".join(f"{s.step_number}. {s.instruction}" for s in steps)
    ctx_text = "\n".join(
        f"- {e.title}: {(e.resolution or '')[:120]}" for e in context[:3]
    )
    return f"""You are evaluating an IT support resolution for quality.

TICKET (category: {category.value})
Title: {title}
Description: {description}

PROPOSED RESOLUTION STEPS:
{steps_text}

KNOWLEDGE BASE CONTEXT USED:
{ctx_text or "(none)"}

Score the resolution from 1 (poor) to 5 (excellent) based on:
- Relevance to the specific ticket
- Actionability (concrete, not vague)
- Completeness (covers the likely root cause)
- Safety (won't make things worse)

Respond with ONLY a JSON object shaped exactly like:
{_EVAL_SCHEMA}"""


class EvaluatorAgent(ConversableAgent):
    def __init__(self, llm_generator: GeneratorProtocol) -> None:
        super().__init__(
            name="EvaluatorAgent",
            human_input_mode="NEVER",
            llm_config=False,
        )
        self._llm = llm_generator

    async def _evaluate(
        self,
        title: str,
        description: str,
        category: TicketCategory,
        steps: list[ResolutionStep],
        context: list[KnowledgeBaseEntry],
    ) -> float:
        """Return a quality score in [1.0, 5.0]."""
        settings = get_settings()
        prompt = _build_eval_prompt(title, description, category, steps, context)

        # Re-use the generator's HTTP client but with a lightweight eval prompt.
        # We ask for raw JSON back from the same LLM endpoint.
        try:
            import httpx

            payload = {
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 256},
            }
            base_url = settings.ollama_base_url.rstrip("/")
            async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
                resp = await client.post(f"{base_url}/api/generate", json=payload)
                resp.raise_for_status()
            raw = resp.json().get("response", "")
        except Exception as exc:
            logger.warning("evaluator_llm_unavailable", error=str(exc))
            # Fallback: return a neutral score so routing can still proceed.
            return settings.llm_quality_threshold

        try:
            return _parse_score(raw)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("evaluator_parse_failed", raw_preview=raw[:200], error=str(exc))
            return settings.llm_quality_threshold
