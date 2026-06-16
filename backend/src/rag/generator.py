"""LLM resolution generator behind a single protocol.

Two concrete implementations — `OllamaGenerator` (default, local) and
`ClaudeGenerator` (when LLM_PROVIDER=claude). Both request a **JSON array**
of `{"step_number": N, "instruction": "..."}` objects (audit fix — v1 returned
free markdown that clients had to regex-parse, docs/03_BACKEND_DESIGN.md §53).

JSON parsing failure with caught, specific exceptions only (audit fix M1).
"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx
from pydantic import ValidationError

from src.core.config import get_settings
from src.core.exceptions import AppBaseException
from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry, ResolutionStep, TicketCategory

logger = get_logger(__name__)

_STEP_SCHEMA = (
    '[{"step_number": 1, "instruction": "..."}, {"step_number": 2, "instruction": "..."}, ...]'
)


class LLMUnavailableError(AppBaseException):
    code = "LLM_UNAVAILABLE"
    http_status = 503

    def __init__(self, message: str) -> None:
        super().__init__(message)


class GeneratorProtocol(Protocol):
    async def generate(
        self,
        ticket_title: str,
        ticket_description: str,
        category: TicketCategory,
        context_entries: list[KnowledgeBaseEntry],
    ) -> list[ResolutionStep]: ...


def _build_prompt(
    title: str,
    description: str,
    category: TicketCategory,
    context_entries: list[KnowledgeBaseEntry],
) -> str:
    context_block = "\n\n".join(
        f"--- KB Entry {i+1} ---\nTitle: {e.title}\nResolution:\n{e.resolution}"
        for i, e in enumerate(context_entries)
        if e.resolution
    )
    return f"""You are an expert IT support engineer resolving a {category.value} ticket.

TICKET TITLE: {title}
TICKET DESCRIPTION: {description}

RELEVANT KNOWLEDGE BASE ENTRIES:
{context_block or "(none)"}

Based on the ticket and knowledge base, provide a step-by-step resolution plan.

Respond with ONLY a JSON array — no markdown, no commentary — shaped exactly like:
{_STEP_SCHEMA}

Each step must be a concrete, actionable instruction. Use 3-7 steps."""


def _parse_steps(raw: str) -> list[ResolutionStep]:
    """Extract and validate the JSON step array from raw LLM output."""
    text = raw.strip()
    # Strip markdown code fences if present
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON array found", text, 0)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise
    steps = []
    for item in data:
        try:
            steps.append(ResolutionStep.model_validate(item))
        except ValidationError as exc:
            logger.warning("step_validation_failed", error=str(exc))
    if not steps:
        raise json.JSONDecodeError("No valid steps parsed", text, 0)
    return steps


class OllamaGenerator:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self._timeout = settings.ollama_timeout_seconds
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    async def generate(
        self,
        ticket_title: str,
        ticket_description: str,
        category: TicketCategory,
        context_entries: list[KnowledgeBaseEntry],
    ) -> list[ResolutionStep]:
        prompt = _build_prompt(ticket_title, ticket_description, category, context_entries)
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self._temperature, "num_predict": self._max_tokens},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise LLMUnavailableError(f"Ollama request failed: {exc}") from exc

        raw = resp.json().get("response", "")
        try:
            return _parse_steps(raw)
        except json.JSONDecodeError as exc:
            logger.error("ollama_json_parse_failed", raw_preview=raw[:200], error=str(exc))
            raise LLMUnavailableError("Ollama returned unparseable JSON.") from exc


class ClaudeGenerator:
    def __init__(self) -> None:
        import anthropic

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise LLMUnavailableError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    async def generate(
        self,
        ticket_title: str,
        ticket_description: str,
        category: TicketCategory,
        context_entries: list[KnowledgeBaseEntry],
    ) -> list[ResolutionStep]:
        prompt = _build_prompt(ticket_title, ticket_description, category, context_entries)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise LLMUnavailableError(f"Claude API request failed: {exc}") from exc

        raw = "".join(b.text for b in response.content if b.type == "text")
        try:
            return _parse_steps(raw)
        except json.JSONDecodeError as exc:
            logger.error("claude_json_parse_failed", raw_preview=raw[:200], error=str(exc))
            raise LLMUnavailableError("Claude returned unparseable JSON.") from exc


def build_generator() -> GeneratorProtocol:
    settings = get_settings()
    if settings.llm_provider == "claude":
        return ClaudeGenerator()
    return OllamaGenerator()
