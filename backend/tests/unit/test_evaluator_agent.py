"""Unit tests for EvaluatorAgent (src/agents/evaluator_agent.py).

Tests score parsing, clamping, fallback behaviour, and the LLM call delegation.
No real LLM or DB calls are made.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.evaluator_agent import EvaluatorAgent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings() -> MagicMock:
    s = MagicMock()
    return s


def _make_agent(llm_response: str = "", llm_error: Exception | None = None) -> EvaluatorAgent:
    llm = AsyncMock()
    if llm_error:
        llm.generate = AsyncMock(side_effect=llm_error)
    else:
        llm.generate = AsyncMock(return_value=llm_response)

    repo = AsyncMock()
    settings = _make_settings()
    return EvaluatorAgent(llm_generator=llm, ticket_repo=repo, settings=settings)


def _ticket_id() -> uuid.UUID:
    return uuid.uuid4()


# ── JSON parsing — happy path ─────────────────────────────────────────────────


class TestScoreParsing:
    def test_valid_json_parses_correctly(self):
        agent = _make_agent()
        score, dims = agent._parse_scores(
            '{"relevance": 4, "completeness": 3, "actionability": 5}',
            _ticket_id(),
        )
        assert dims["relevance"] == pytest.approx(4.0)
        assert dims["completeness"] == pytest.approx(3.0)
        assert dims["actionability"] == pytest.approx(5.0)
        assert score == pytest.approx(4.0, abs=1e-4)

    def test_float_scores_accepted(self):
        agent = _make_agent()
        score, dims = agent._parse_scores(
            '{"relevance": 4.5, "completeness": 4.0, "actionability": 3.8}',
            _ticket_id(),
        )
        expected = (4.5 + 4.0 + 3.8) / 3
        assert score == pytest.approx(expected, abs=1e-4)

    def test_json_embedded_in_prose_still_parsed(self):
        agent = _make_agent()
        response = (
            "Here is my evaluation:\n"
            '{"relevance": 4, "completeness": 4, "actionability": 4}\n'
            "I hope this helps."
        )
        score, _ = agent._parse_scores(response, _ticket_id())
        assert score == pytest.approx(4.0, abs=1e-4)

    def test_quality_score_is_mean_of_three_dimensions(self):
        agent = _make_agent()
        score, _ = agent._parse_scores(
            '{"relevance": 5, "completeness": 3, "actionability": 4}',
            _ticket_id(),
        )
        assert score == pytest.approx((5 + 3 + 4) / 3, abs=1e-4)


# ── Clamping ──────────────────────────────────────────────────────────────────


class TestScoreClamping:
    def test_score_above_5_clamped_to_5(self):
        agent = _make_agent()
        _, dims = agent._parse_scores(
            '{"relevance": 10, "completeness": 4, "actionability": 4}',
            _ticket_id(),
        )
        assert dims["relevance"] == pytest.approx(5.0)

    def test_negative_score_clamped_to_0(self):
        agent = _make_agent()
        _, dims = agent._parse_scores(
            '{"relevance": -1, "completeness": 3, "actionability": 3}',
            _ticket_id(),
        )
        assert dims["relevance"] == pytest.approx(0.0)

    def test_all_dimensions_clamped_independently(self):
        agent = _make_agent()
        _, dims = agent._parse_scores(
            '{"relevance": 99, "completeness": -5, "actionability": 3}',
            _ticket_id(),
        )
        assert dims["relevance"] == pytest.approx(5.0)
        assert dims["completeness"] == pytest.approx(0.0)
        assert dims["actionability"] == pytest.approx(3.0)


# ── Fallback on parse failures ────────────────────────────────────────────────


class TestParseFallback:
    def test_invalid_json_returns_zero_score(self):
        agent = _make_agent()
        score, dims = agent._parse_scores("This is not JSON at all.", _ticket_id())
        assert score == pytest.approx(0.0)
        assert all(v == 0.0 for v in dims.values())

    def test_empty_response_returns_zero_score(self):
        agent = _make_agent()
        score, dims = agent._parse_scores("", _ticket_id())
        assert score == pytest.approx(0.0)

    def test_malformed_json_returns_zero_score(self):
        agent = _make_agent()
        score, _ = agent._parse_scores('{"relevance": 4, "completeness": }', _ticket_id())
        assert score == pytest.approx(0.0)

    def test_missing_keys_default_to_zero(self):
        agent = _make_agent()
        score, dims = agent._parse_scores('{"relevance": 4}', _ticket_id())
        assert dims["completeness"] == pytest.approx(0.0)
        assert dims["actionability"] == pytest.approx(0.0)
        assert score == pytest.approx(4.0 / 3, abs=1e-4)


# ── LLM call failure fallback ─────────────────────────────────────────────────


class TestLLMFailureFallback:
    async def test_llm_exception_returns_zero_score(self):
        agent = _make_agent(llm_error=RuntimeError("LLM timeout"))
        msg = {
            "type": "EVALUATE",
            "ticket_id": str(uuid.uuid4()),
            "title": "Test",
            "description": "Test desc",
            "resolution_text": "Step 1: Restart.",
        }
        result = await agent._evaluate(msg)
        assert result["quality_score"] == pytest.approx(0.0)
        assert result["type"] == "EVALUATION_RESULT"

    async def test_llm_failure_does_not_raise(self):
        agent = _make_agent(llm_error=ConnectionError("refused"))
        msg = {
            "type": "EVALUATE",
            "ticket_id": str(uuid.uuid4()),
            "title": "Test",
            "description": "Test",
            "resolution_text": "Fix it.",
        }
        # Must not raise
        result = await agent._evaluate(msg)
        assert isinstance(result, dict)


# ── Full evaluate() happy path ────────────────────────────────────────────────


class TestEvaluateHappyPath:
    async def test_evaluate_returns_evaluation_result_type(self):
        agent = _make_agent(
            llm_response='{"relevance": 4, "completeness": 4, "actionability": 4}'
        )
        msg = {
            "type": "EVALUATE",
            "ticket_id": str(uuid.uuid4()),
            "title": "VPN down",
            "description": "Cannot connect.",
            "resolution_text": "Step 1: Restart VPN.",
        }
        result = await agent._evaluate(msg)
        assert result["type"] == "EVALUATION_RESULT"
        assert result["quality_score"] == pytest.approx(4.0, abs=1e-4)

    async def test_evaluate_includes_dimension_scores(self):
        agent = _make_agent(
            llm_response='{"relevance": 5, "completeness": 3, "actionability": 4}'
        )
        msg = {
            "type": "EVALUATE",
            "ticket_id": str(uuid.uuid4()),
            "title": "DB slow",
            "description": "Queries slow.",
            "resolution_text": "Kill blocking queries.",
        }
        result = await agent._evaluate(msg)
        assert "dimension_scores" in result
        assert result["dimension_scores"]["relevance"] == pytest.approx(5.0)
