"""AutoGen LLM-as-judge evaluator agent.

Sends the generated resolution to an LLM and asks it to score three
quality dimensions (relevance, completeness, actionability) on a 0–5 scale.
Returns the mean score as ``quality_score``.

Falls back to ``quality_score=0.0`` if the LLM response cannot be parsed as
valid JSON — this triggers ESCALATED routing in the downstream router.
Status transition: ``GENERATING → EVALUATING``.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

import autogen

from src.core.logging import get_logger
from src.db.models import TicketStatus

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.db.repositories.ticket_repo import TicketRepository
    from src.rag.generator import LLMGeneratorProtocol

logger = get_logger(__name__)

_EVAL_PROMPT_TEMPLATE = """\
You are an IT resolution quality evaluator.
Rate this resolution on 3 dimensions, each scored 0–5:
- relevance: Does it address the specific issue described?
- completeness: Are all necessary steps included?
- actionability: Are steps clear and immediately executable?

Ticket: {title}
Description: {description}
Resolution: {resolution_text}

Respond ONLY with valid JSON, no other text:
{{"relevance": <0-5>, "completeness": <0-5>, "actionability": <0-5>}}"""


class EvaluatorAgent(autogen.ConversableAgent):
    """AutoGen agent that scores a generated resolution via LLM-as-judge.

    Uses the same :class:`~src.rag.generator.LLMGeneratorProtocol` backend
    as the RAG generator (Ollama or Claude), but with a structured evaluation
    prompt instead of a resolution-generation prompt.

    Args:
        llm_generator: :class:`~src.rag.generator.LLMGeneratorProtocol`
            instance for making the evaluation call.
        ticket_repo: For updating ticket status to EVALUATING.
        settings: Application settings.
    """

    def __init__(
        self,
        llm_generator: "LLMGeneratorProtocol",
        ticket_repo: "TicketRepository",
        settings: "Settings",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="EvaluatorAgent",
            human_input_mode="NEVER",
            llm_config=False,
            **kwargs,
        )
        self._llm = llm_generator
        self._ticket_repo = ticket_repo
        self._settings = settings

    async def _evaluate(self, msg: dict) -> dict:
        """Call the LLM evaluator and parse the quality score."""
        ticket_id = uuid.UUID(msg["ticket_id"])
        title: str = msg["title"]
        description: str = msg["description"]
        resolution_text: str = msg["resolution_text"]

        await self._ticket_repo.update_status(ticket_id, TicketStatus.EVALUATING)

        prompt = _EVAL_PROMPT_TEMPLATE.format(
            title=title,
            description=description,
            resolution_text=resolution_text,
        )

        try:
            llm_response = await self._llm.generate(prompt)
        except Exception as exc:  # intentionally broad — evaluator must never hard-fail
            logger.warning(
                "EvaluatorAgent: LLM call failed — defaulting to score 0.0",
                extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
            )
            return self._fallback_result(ticket_id)

        quality_score, dimension_scores = self._parse_scores(llm_response, ticket_id)

        logger.info(
            "EvaluatorAgent: evaluation complete",
            extra={
                "metadata": {
                    "ticket_id": str(ticket_id),
                    "quality_score": quality_score,
                    "dimensions": dimension_scores,
                }
            },
        )

        return {
            "type": "EVALUATION_RESULT",
            "ticket_id": str(ticket_id),
            "quality_score": quality_score,
            "dimension_scores": dimension_scores,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _parse_scores(
        self,
        response: str,
        ticket_id: uuid.UUID,
    ) -> tuple[float, dict[str, float]]:
        """Extract and validate dimension scores from the LLM JSON response.

        Uses a regex to find the first JSON object in the response so that
        leading/trailing prose from the LLM does not cause a parse failure.

        Args:
            response: Raw string from the LLM.
            ticket_id: Used for warning logs on parse failure.

        Returns:
            ``(quality_score, dimension_scores)`` — quality_score is 0.0 on
            any failure.
        """
        match = re.search(r"\{[^}]*\}", response, re.DOTALL)
        if not match:
            logger.warning(
                "EvaluatorAgent: no JSON object found in LLM response",
                extra={"metadata": {"ticket_id": str(ticket_id), "response": response[:200]}},
            )
            return 0.0, {"relevance": 0.0, "completeness": 0.0, "actionability": 0.0}

        try:
            raw = json.loads(match.group())
        except json.JSONDecodeError as exc:
            logger.warning(
                "EvaluatorAgent: JSON parse failed",
                extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
            )
            return 0.0, {"relevance": 0.0, "completeness": 0.0, "actionability": 0.0}

        def _clamp(v: Any) -> float:
            try:
                return max(0.0, min(5.0, float(v)))
            except (TypeError, ValueError):
                return 0.0

        relevance = _clamp(raw.get("relevance", 0))
        completeness = _clamp(raw.get("completeness", 0))
        actionability = _clamp(raw.get("actionability", 0))

        quality_score = round((relevance + completeness + actionability) / 3, 4)
        dimension_scores = {
            "relevance": relevance,
            "completeness": completeness,
            "actionability": actionability,
        }
        return quality_score, dimension_scores

    @staticmethod
    def _fallback_result(ticket_id: uuid.UUID) -> dict:
        return {
            "type": "EVALUATION_RESULT",
            "ticket_id": str(ticket_id),
            "quality_score": 0.0,
            "dimension_scores": {"relevance": 0.0, "completeness": 0.0, "actionability": 0.0},
        }
