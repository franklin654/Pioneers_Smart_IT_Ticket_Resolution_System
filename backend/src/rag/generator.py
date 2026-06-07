"""LLM-backed resolution generator for the RAG pipeline.

Provides two concrete LLM backends behind a common Protocol so callers
(the agentic orchestrator in Phase 5) never depend on a specific SDK:

    - :class:`OllamaGenerator` — uses the ``ollama`` Python SDK (AsyncClient)
    - :class:`ClaudeGenerator` — uses the ``anthropic`` Python SDK (AsyncAnthropic)

Both are created via :class:`LLMGeneratorFactory` which reads ``LLM_BACKEND``
from settings.  The high-level :class:`RAGGenerator` ties everything together:
it formats a category-specific prompt that includes the MMR-reranked KB context
and delegates generation to whichever backend is active.

Prompt templates live in ``_PROMPT_TEMPLATES`` — one per :class:`TicketCategory`.
A fallback generic template is used if a category is somehow unmapped.
"""

from __future__ import annotations

import anthropic
import ollama

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.core.exceptions import LLMUnavailableError
from src.core.logging import get_logger
from src.db.models import TicketCategory
from src.rag.retriever import RetrievedEntry

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)

# ── Prompt templates ───────────────────────────────────────────────────────────

_GENERIC_PREAMBLE = (
    "You are an experienced IT support specialist. "
    "Provide a clear, concise, step-by-step resolution for the ticket below. "
    "Be specific, actionable, and use numbered steps."
)

_PROMPT_TEMPLATES: dict[TicketCategory, str] = {
    TicketCategory.INFRASTRUCTURE: (
        "You are an IT infrastructure specialist with expertise in servers, "
        "virtual machines, storage, and on-premises hardware. "
        "Diagnose the issue methodically: check hardware health, system logs, and "
        "resource utilisation first. Provide a step-by-step resolution with rollback "
        "steps where applicable."
    ),
    TicketCategory.APPLICATION: (
        "You are an application support engineer with expertise in diagnosing "
        "software defects, dependency conflicts, and configuration issues. "
        "Focus on log analysis, environment differences, and configuration validation. "
        "Provide a step-by-step resolution, noting any restart or deployment steps."
    ),
    TicketCategory.SECURITY: (
        "You are a cybersecurity incident responder. "
        "Prioritise containment first, then investigation, then remediation. "
        "If the issue involves a potential breach or active threat, include isolation "
        "steps before any diagnostic commands. Follow least-privilege principles in "
        "every remediation step."
    ),
    TicketCategory.DATABASE: (
        "You are a database administrator experienced with PostgreSQL, MySQL, "
        "and MSSQL. Focus on query performance, locking, replication lag, and "
        "backup integrity. Provide safe, non-destructive diagnostic steps first, "
        "then the remediation path with explicit rollback options."
    ),
    TicketCategory.ACCESS_MANAGEMENT: (
        "You are an identity and access management specialist. "
        "Verify the user's identity and authorisation level before making any changes. "
        "Follow the principle of least privilege. Document each permission change and "
        "provide both the grant and the corresponding revocation command."
    ),
    TicketCategory.NETWORK: (
        "You are a network engineer experienced with routing, switching, VPNs, "
        "and DNS. Use a layered troubleshooting approach (physical → data link → "
        "network → transport → application). Include specific diagnostic commands "
        "(ping, traceroute, nslookup, netstat) and expected output descriptions."
    ),
}

_FALLBACK_PREAMBLE = _GENERIC_PREAMBLE


def _get_preamble(category: TicketCategory) -> str:
    return _PROMPT_TEMPLATES.get(category, _FALLBACK_PREAMBLE)


# ── Protocol ───────────────────────────────────────────────────────────────────


@runtime_checkable
class LLMGeneratorProtocol(Protocol):
    """Interface that all LLM backends must satisfy."""

    async def generate(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the generated text.

        Args:
            prompt: Fully formatted prompt string.

        Returns:
            Raw text response from the model.

        Raises:
            LLMUnavailableError: If the backend is unreachable or returns an error.
        """
        ...


# ── Concrete backends ──────────────────────────────────────────────────────────


class OllamaGenerator:
    """Generates resolutions using the Ollama SDK (AsyncClient).

    Args:
        settings: Application settings; reads ``ollama_base_url``,
            ``ollama_model``, ``llm_temperature``, ``llm_max_tokens``.
    """

    def __init__(self, settings: "Settings") -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    async def generate(self, prompt: str) -> str:
        """Call the Ollama AsyncClient and return the generated text.

        Args:
            prompt: Fully formatted prompt string.

        Returns:
            Generated text from the Ollama model.

        Raises:
            LLMUnavailableError: On connection failure or API error.
        """
        try:
            client = ollama.AsyncClient(host=self._base_url)
            response = await client.generate(
                model=self._model,
                prompt=prompt,
                options={
                    "temperature": self._temperature,
                    "num_predict": self._max_tokens,
                },
            )
            text: str = response.response
            logger.info(
                "Ollama generation complete",
                extra={"metadata": {"model": self._model, "chars": len(text)}},
            )
            return text
        except ollama.ResponseError as exc:
            raise LLMUnavailableError(
                backend="ollama",
                reason=f"API error {exc.status_code}: {exc.error}",
            ) from exc
        except Exception as exc:
            raise LLMUnavailableError(
                backend="ollama",
                reason=str(exc),
            ) from exc


class ClaudeGenerator:
    """Generates resolutions using the Anthropic Messages API.

    Args:
        settings: Application settings; reads ``anthropic_api_key``,
            ``claude_model``, ``llm_temperature``, ``llm_max_tokens``.
    """

    def __init__(self, settings: "Settings") -> None:
        self._api_key = settings.anthropic_api_key
        self._model = settings.claude_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    async def generate(self, prompt: str) -> str:
        """Call the Anthropic AsyncAnthropic client and return the generated text.

        Args:
            prompt: Fully formatted prompt string.

        Returns:
            Generated text from Claude.

        Raises:
            LLMUnavailableError: On API connection failure or response error.
        """
        try:
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            message = await client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            text: str = message.content[0].text
            logger.info(
                "Claude generation complete",
                extra={"metadata": {"model": self._model, "chars": len(text)}},
            )
            return text
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(
                backend="claude",
                reason=f"Connection error: {exc}",
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailableError(
                backend="claude",
                reason=f"API error {exc.status_code}: {exc.message}",
            ) from exc
        except Exception as exc:
            raise LLMUnavailableError(
                backend="claude",
                reason=str(exc),
            ) from exc


# ── Factory ────────────────────────────────────────────────────────────────────


class LLMGeneratorFactory:
    """Creates the appropriate LLM generator based on ``settings.llm_backend``."""

    @staticmethod
    def from_settings(settings: "Settings") -> LLMGeneratorProtocol:
        """Construct an LLM generator from application settings.

        Args:
            settings: Application settings; reads ``llm_backend``.

        Returns:
            :class:`OllamaGenerator` or :class:`ClaudeGenerator`.

        Raises:
            ValueError: If ``llm_backend`` is not ``"ollama"`` or ``"claude"``
                (defensive — Settings already validates via ``Literal``).
        """
        if settings.llm_backend == "ollama":
            return OllamaGenerator(settings)
        if settings.llm_backend == "claude":
            return ClaudeGenerator(settings)
        raise ValueError(f"Unknown LLM backend: {settings.llm_backend!r}")


# ── High-level orchestrator ────────────────────────────────────────────────────


class RAGGenerator:
    """Generates ticket resolutions by combining KB context with LLM generation.

    Builds a category-specific prompt that includes the MMR-reranked KB entries
    as context, then calls the configured LLM backend.

    Args:
        llm: An :class:`LLMGeneratorProtocol` implementation.
        settings: Application settings.
    """

    def __init__(
        self,
        llm: LLMGeneratorProtocol,
        settings: "Settings",
    ) -> None:
        self._llm = llm
        self._settings = settings

    async def generate(
        self,
        ticket_title: str,
        ticket_description: str,
        category: TicketCategory,
        retrieved_entries: list[RetrievedEntry],
    ) -> str:
        """Generate a resolution for a ticket using retrieved KB context.

        Args:
            ticket_title: Clean ticket title (no PII).
            ticket_description: PII-masked ticket description.
            category: Predicted ticket category (used to select the prompt
                template).
            retrieved_entries: MMR-reranked KB entries (top-k) to include as
                context.  May be empty if the knowledge base is empty.

        Returns:
            Raw LLM-generated resolution text.

        Raises:
            LLMUnavailableError: If the LLM backend fails.
        """
        prompt = self._build_prompt(
            ticket_title=ticket_title,
            ticket_description=ticket_description,
            category=category,
            retrieved_entries=retrieved_entries,
        )
        logger.debug(
            "Sending prompt to LLM",
            extra={
                "metadata": {
                    "category": category.value,
                    "context_entries": len(retrieved_entries),
                    "prompt_chars": len(prompt),
                }
            },
        )
        return await self._llm.generate(prompt)

    def _build_prompt(
        self,
        ticket_title: str,
        ticket_description: str,
        category: TicketCategory,
        retrieved_entries: list[RetrievedEntry],
    ) -> str:
        """Format the category-specific prompt with retrieved KB context.

        The prompt structure is:
        1. Domain-specific preamble (selected by category).
        2. Relevant past resolutions (if any retrieved entries exist).
        3. Current ticket details.
        4. Instruction line to begin the resolution.

        Args:
            ticket_title: Ticket title.
            ticket_description: Masked description.
            category: Ticket category (selects the preamble template).
            retrieved_entries: MMR-reranked KB entries to use as context.

        Returns:
            Fully formatted prompt string ready to send to the LLM.
        """
        preamble = _get_preamble(category)
        parts: list[str] = [preamble, ""]

        if retrieved_entries:
            parts.append("=== Relevant Past Resolutions ===")
            for i, entry in enumerate(retrieved_entries, start=1):
                parts.append(
                    f"{i}. Issue: {entry.entry.title}\n"
                    f"   Resolution: {entry.entry.resolution}"
                )
            parts.append("")

        parts.extend([
            "=== Current Ticket ===",
            f"Title: {ticket_title}",
            f"Description: {ticket_description}",
            "",
            "=== Your Resolution ===",
            "Provide a step-by-step resolution:",
        ])

        return "\n".join(parts)
