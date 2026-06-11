"""Unit tests for the RAG generator (src/rag/generator.py).

Tests cover:
    - LLMGeneratorFactory backend selection
    - OllamaGenerator happy path and error handling (mocked ollama SDK)
    - ClaudeGenerator happy path and error handling (mocked anthropic SDK)
    - RAGGenerator._build_prompt() content and structure
    - RAGGenerator.generate() delegation to the LLM backend
    - Prompt template coverage (one template per TicketCategory)

No real LLM calls are made; all backends are mocked.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import LLMUnavailableError
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.rag.generator import (
    ClaudeGenerator,
    LLMGeneratorFactory,
    OllamaGenerator,
    RAGGenerator,
    _PROMPT_TEMPLATES,
)
from src.rag.retriever import RetrievedEntry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(
    llm_backend: str = "ollama",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "mistral:7b-instruct",
    ollama_timeout: int = 30,
    anthropic_api_key: str = "sk-ant-test",
    claude_model: str = "claude-haiku-4-5-20251001",
    llm_temperature: float = 0.1,
    llm_max_tokens: int = 512,
) -> MagicMock:
    s = MagicMock()
    s.llm_backend = llm_backend
    s.ollama_base_url = ollama_base_url
    s.ollama_model = ollama_model
    s.ollama_timeout = ollama_timeout
    s.anthropic_api_key = anthropic_api_key
    s.claude_model = claude_model
    s.llm_temperature = llm_temperature
    s.llm_max_tokens = llm_max_tokens
    return s


def _make_retrieved_entry(title: str = "Issue title", resolution: str = "Fix it") -> RetrievedEntry:
    kb = MagicMock(spec=KnowledgeBaseEntry)
    kb.id = uuid.uuid4()
    kb.title = title
    kb.resolution = resolution
    kb.category = TicketCategory.NETWORK
    return RetrievedEntry(entry=kb, combined_score=0.8)


# ── Factory tests ─────────────────────────────────────────────────────────────


class TestLLMGeneratorFactory:
    def test_ollama_backend_returns_ollama_generator(self):
        settings = _make_settings(llm_backend="ollama")
        generator = LLMGeneratorFactory.from_settings(settings)
        assert isinstance(generator, OllamaGenerator)

    def test_claude_backend_returns_claude_generator(self):
        settings = _make_settings(llm_backend="claude")
        generator = LLMGeneratorFactory.from_settings(settings)
        assert isinstance(generator, ClaudeGenerator)

    def test_unknown_backend_raises_value_error(self):
        settings = _make_settings(llm_backend="gpt4")
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            LLMGeneratorFactory.from_settings(settings)


# ── OllamaGenerator tests ─────────────────────────────────────────────────────


class TestOllamaGenerator:
    async def test_successful_generate_returns_text(self):
        settings = _make_settings()
        generator = OllamaGenerator(settings)

        mock_response = MagicMock()
        mock_response.response = "Restart the VPN service."

        mock_client = AsyncMock()
        mock_client.generate.return_value = mock_response

        with patch("src.rag.generator.ollama.AsyncClient", return_value=mock_client):
            result = await generator.generate("What is wrong with VPN?")

        assert result == "Restart the VPN service."

    async def test_generate_passes_model_and_options(self):
        settings = _make_settings(ollama_model="mistral:7b-instruct", llm_temperature=0.2, llm_max_tokens=256)
        generator = OllamaGenerator(settings)

        mock_response = MagicMock()
        mock_response.response = "ok"
        mock_client = AsyncMock()
        mock_client.generate.return_value = mock_response

        with patch("src.rag.generator.ollama.AsyncClient", return_value=mock_client):
            await generator.generate("prompt text")

        call_kwargs = mock_client.generate.call_args.kwargs
        assert call_kwargs["model"] == "mistral:7b-instruct"
        assert call_kwargs["options"]["temperature"] == pytest.approx(0.2)
        assert call_kwargs["options"]["num_predict"] == 256

    async def test_ollama_response_error_raises_llm_unavailable(self):
        import ollama as ollama_sdk

        settings = _make_settings()
        generator = OllamaGenerator(settings)

        mock_client = AsyncMock()
        mock_client.generate.side_effect = ollama_sdk.ResponseError("model not found", status_code=404)

        with patch("src.rag.generator.ollama.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMUnavailableError) as exc_info:
                await generator.generate("test prompt")

        assert exc_info.value.detail["backend"] == "ollama"

    async def test_ollama_generic_exception_raises_llm_unavailable(self):
        settings = _make_settings()
        generator = OllamaGenerator(settings)

        mock_client = AsyncMock()
        mock_client.generate.side_effect = ConnectionRefusedError("connection refused")

        with patch("src.rag.generator.ollama.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMUnavailableError) as exc_info:
                await generator.generate("test prompt")

        assert exc_info.value.detail["backend"] == "ollama"


# ── ClaudeGenerator tests ─────────────────────────────────────────────────────


class TestClaudeGenerator:
    async def test_successful_generate_returns_text(self):
        settings = _make_settings(llm_backend="claude")
        generator = ClaudeGenerator(settings)

        mock_content = MagicMock()
        mock_content.text = "Check the firewall rules."
        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch("src.rag.generator.anthropic.AsyncAnthropic", return_value=mock_client):
            result = await generator.generate("Firewall issue detected.")

        assert result == "Check the firewall rules."

    async def test_generate_passes_model_and_params(self):
        settings = _make_settings(llm_backend="claude", claude_model="claude-haiku-4-5-20251001", llm_max_tokens=512)
        generator = ClaudeGenerator(settings)

        mock_content = MagicMock()
        mock_content.text = "ok"
        mock_message = MagicMock()
        mock_message.content = [mock_content]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch("src.rag.generator.anthropic.AsyncAnthropic", return_value=mock_client):
            await generator.generate("test prompt")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 512

    async def test_api_connection_error_raises_llm_unavailable(self):
        import anthropic as anthropic_sdk

        settings = _make_settings(llm_backend="claude")
        generator = ClaudeGenerator(settings)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic_sdk.APIConnectionError(request=MagicMock())
        )

        with patch("src.rag.generator.anthropic.AsyncAnthropic", return_value=mock_client):
            with pytest.raises(LLMUnavailableError) as exc_info:
                await generator.generate("test prompt")

        assert exc_info.value.detail["backend"] == "claude"

    async def test_api_status_error_raises_llm_unavailable(self):
        import anthropic as anthropic_sdk

        settings = _make_settings(llm_backend="claude")
        generator = ClaudeGenerator(settings)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic_sdk.RateLimitError(
                message="rate limited", response=mock_response, body={}
            )
        )

        with patch("src.rag.generator.anthropic.AsyncAnthropic", return_value=mock_client):
            with pytest.raises(LLMUnavailableError) as exc_info:
                await generator.generate("test prompt")

        assert exc_info.value.detail["backend"] == "claude"


# ── RAGGenerator._build_prompt tests ─────────────────────────────────────────


class TestRAGGeneratorBuildPrompt:
    def _make_rag_generator(self) -> RAGGenerator:
        llm = AsyncMock()
        settings = _make_settings()
        return RAGGenerator(llm=llm, settings=settings)

    def test_prompt_contains_ticket_title(self):
        rag = self._make_rag_generator()
        prompt = rag._build_prompt(
            ticket_title="VPN authentication failure",
            ticket_description="Users cannot connect.",
            category=TicketCategory.NETWORK,
            retrieved_entries=[],
        )
        assert "VPN authentication failure" in prompt

    def test_prompt_contains_ticket_description(self):
        rag = self._make_rag_generator()
        prompt = rag._build_prompt(
            ticket_title="DB slow",
            ticket_description="Queries taking over 30 seconds.",
            category=TicketCategory.DATABASE,
            retrieved_entries=[],
        )
        assert "Queries taking over 30 seconds." in prompt

    def test_prompt_includes_retrieved_entry_resolution(self):
        rag = self._make_rag_generator()
        entry = _make_retrieved_entry(title="Past VPN issue", resolution="Reset VPN config")
        prompt = rag._build_prompt(
            ticket_title="VPN down",
            ticket_description="Cannot connect.",
            category=TicketCategory.NETWORK,
            retrieved_entries=[entry],
        )
        assert "Reset VPN config" in prompt

    def test_prompt_includes_retrieved_entry_title(self):
        rag = self._make_rag_generator()
        entry = _make_retrieved_entry(title="Known DB lock issue", resolution="Kill blocking queries")
        prompt = rag._build_prompt(
            ticket_title="DB locked",
            ticket_description="Transactions blocked.",
            category=TicketCategory.DATABASE,
            retrieved_entries=[entry],
        )
        assert "Known DB lock issue" in prompt

    def test_prompt_with_empty_entries_still_valid(self):
        rag = self._make_rag_generator()
        prompt = rag._build_prompt(
            ticket_title="Unknown error",
            ticket_description="Something went wrong.",
            category=TicketCategory.APPLICATION,
            retrieved_entries=[],
        )
        assert "Unknown error" in prompt
        assert "Something went wrong." in prompt
        # No context section heading when no entries
        assert "Relevant Past Resolutions" not in prompt

    def test_multiple_entries_all_appear_in_prompt(self):
        rag = self._make_rag_generator()
        entries = [
            _make_retrieved_entry(title=f"Issue {i}", resolution=f"Fix {i}")
            for i in range(3)
        ]
        prompt = rag._build_prompt(
            ticket_title="Multi-context test",
            ticket_description="Check all entries.",
            category=TicketCategory.SECURITY,
            retrieved_entries=entries,
        )
        for i in range(3):
            assert f"Fix {i}" in prompt


# ── Prompt template coverage ──────────────────────────────────────────────────


class TestPromptTemplateCoverage:
    def test_every_ticket_category_has_a_template(self):
        """No TicketCategory should trigger the generic fallback due to a missing key."""
        for cat in TicketCategory:
            assert cat in _PROMPT_TEMPLATES, f"Missing prompt template for {cat.value}"

    def test_all_templates_are_non_empty(self):
        for cat, template in _PROMPT_TEMPLATES.items():
            assert template.strip(), f"Empty template for {cat.value}"


# ── RAGGenerator.generate delegation ─────────────────────────────────────────


class TestRAGGeneratorGenerate:
    async def test_generate_calls_llm_with_built_prompt(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="Step 1: Restart service.")
        settings = _make_settings()
        rag = RAGGenerator(llm=mock_llm, settings=settings)

        entry = _make_retrieved_entry()
        result = await rag.generate(
            ticket_title="Service down",
            ticket_description="Cannot reach endpoint.",
            category=TicketCategory.INFRASTRUCTURE,
            retrieved_entries=[entry],
        )

        assert result == "Step 1: Restart service."
        mock_llm.generate.assert_called_once()
        # The prompt passed should include the ticket title
        prompt_arg = mock_llm.generate.call_args.args[0]
        assert "Service down" in prompt_arg

    async def test_generate_propagates_llm_unavailable_error(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=LLMUnavailableError(backend="ollama", reason="timeout")
        )
        settings = _make_settings()
        rag = RAGGenerator(llm=mock_llm, settings=settings)

        with pytest.raises(LLMUnavailableError):
            await rag.generate(
                ticket_title="Test",
                ticket_description="Test",
                category=TicketCategory.NETWORK,
                retrieved_entries=[],
            )
