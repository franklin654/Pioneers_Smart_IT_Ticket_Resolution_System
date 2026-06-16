"""LLM-as-judge evaluation of generated resolutions.

Scores each resolution on three orthogonal axes (each 1-5):
  - Relevance     — do the steps address the specific ticket?
  - Completeness  — does the plan cover the likely root cause?
  - Actionability — are the instructions concrete and executable?

Gate: overall mean ≥ 3.5 / 5.0

The judge calls the same LLM backend used for generation (Ollama or Claude),
so this evaluator requires the LLM to be running. On judge failure (LLM
unavailable, parse error), the ticket is skipped and a warning is logged.

Usage:
    python evaluation/llm_judge.py
    python evaluation/llm_judge.py --sample 25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from dataclasses import dataclass, field

import httpx

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.models import TicketSource
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)

_SCORE_GATE = 3.5
_DEFAULT_SAMPLE = 50
_RANDOM_SEED = 42

_JUDGE_SCHEMA = (
    '{"relevance": <1-5>, "completeness": <1-5>, "actionability": <1-5>, '
    '"reasoning": "..."}'
)


@dataclass
class TicketScore:
    ticket_id: str
    relevance: float
    completeness: float
    actionability: float

    @property
    def mean(self) -> float:
        return (self.relevance + self.completeness + self.actionability) / 3.0


@dataclass
class JudgeResults:
    scores: list[TicketScore] = field(default_factory=list)
    skipped: int = 0

    @property
    def overall_mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.mean for s in self.scores) / len(self.scores)

    @property
    def relevance_mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.relevance for s in self.scores) / len(self.scores)

    @property
    def completeness_mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.completeness for s in self.scores) / len(self.scores)

    @property
    def actionability_mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.actionability for s in self.scores) / len(self.scores)


def _build_judge_prompt(
    title: str,
    description: str,
    category: str,
    steps: list[dict],
) -> str:
    steps_text = "\n".join(
        f"{s.get('step_number', i + 1)}. {s.get('instruction', '')}"
        for i, s in enumerate(steps)
    )
    return f"""You are an expert IT support QA engineer evaluating a resolution plan.

TICKET (category: {category})
Title: {title}
Description: {description}

PROPOSED RESOLUTION STEPS:
{steps_text}

Score each dimension from 1 (very poor) to 5 (excellent):
- relevance: Do the steps directly address this specific ticket's issue?
- completeness: Does the plan cover the root cause and likely failure modes?
- actionability: Are all instructions concrete, executable, and unambiguous?

Respond with ONLY a JSON object shaped exactly like:
{_JUDGE_SCHEMA}"""


def _parse_judge_response(raw: str) -> tuple[float, float, float]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object found", raw, 0)
    data = json.loads(match.group(0))
    relevance = float(data["relevance"])
    completeness = float(data["completeness"])
    actionability = float(data["actionability"])
    for val in (relevance, completeness, actionability):
        if not 1.0 <= val <= 5.0:
            raise ValueError(f"Score {val} is outside [1, 5]")
    return relevance, completeness, actionability


async def _judge_with_ollama(prompt: str, settings: object) -> str:
    from src.core.config import Settings

    assert isinstance(settings, Settings)
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
    return str(resp.json().get("response", ""))


async def _judge_with_claude(prompt: str, settings: object) -> str:
    import anthropic

    from src.core.config import Settings

    assert isinstance(settings, Settings)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or "")
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


async def _score_ticket(
    ticket_id: str,
    title: str,
    description: str,
    category: str,
    steps: list[dict],
    settings: object,
) -> TicketScore | None:
    from src.core.config import Settings

    assert isinstance(settings, Settings)
    prompt = _build_judge_prompt(title, description, category, steps)
    try:
        if settings.llm_provider == "claude":
            raw = await _judge_with_claude(prompt, settings)
        else:
            raw = await _judge_with_ollama(prompt, settings)
        relevance, completeness, actionability = _parse_judge_response(raw)
        return TicketScore(
            ticket_id=ticket_id,
            relevance=relevance,
            completeness=completeness,
            actionability=actionability,
        )
    except Exception as exc:
        logger.warning("judge_skip", ticket_id=ticket_id, error=str(exc))
        return None


async def _run(sample: int) -> float:
    settings = get_settings()

    async with session_scope() as session:
        repo = TicketRepository(session)
        all_tickets = await repo.get_by_source(TicketSource.WEBHOOK)

    # Filter to tickets with a resolution that has suggested_steps
    candidates = [
        t for t in all_tickets
        if t.resolution is not None and t.resolution.suggested_steps
        and t.category is not None
    ]

    if not candidates:
        raise RuntimeError(
            "No scored WEBHOOK tickets with resolutions found. "
            "Run holdout_eval.py first to process the held-out set."
        )

    rng = random.Random(_RANDOM_SEED)
    sample_tickets = rng.sample(candidates, min(sample, len(candidates)))

    results = JudgeResults()
    for ticket in sample_tickets:
        score = await _score_ticket(
            ticket_id=str(ticket.id),
            title=ticket.title,
            description=ticket.description,
            category=ticket.category.value if ticket.category else "unknown",
            steps=ticket.resolution.suggested_steps or [],  # type: ignore[union-attr]
            settings=settings,
        )
        if score is not None:
            results.scores.append(score)
        else:
            results.skipped += 1

    print("\n" + "=" * 60)
    print("LLM JUDGE — Resolution Quality Evaluation")
    print("=" * 60)
    print(f"Candidates       : {len(candidates)}")
    print(f"Sampled          : {len(sample_tickets)}")
    print(f"Scored           : {len(results.scores)}")
    print(f"Skipped (errors) : {results.skipped}")
    print()
    print(f"Relevance mean       : {results.relevance_mean:.3f} / 5.0")
    print(f"Completeness mean    : {results.completeness_mean:.3f} / 5.0")
    print(f"Actionability mean   : {results.actionability_mean:.3f} / 5.0")
    print(f"Overall mean         : {results.overall_mean:.3f} / 5.0  (gate ≥ {_SCORE_GATE})")
    print("=" * 60)

    logger.info(
        "llm_judge_complete",
        sampled=len(sample_tickets),
        scored=len(results.scores),
        overall_mean=round(results.overall_mean, 3),
        relevance_mean=round(results.relevance_mean, 3),
        completeness_mean=round(results.completeness_mean, 3),
        actionability_mean=round(results.actionability_mean, 3),
    )
    return results.overall_mean


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=_DEFAULT_SAMPLE,
        help="Maximum number of tickets to judge (default: %(default)s)",
    )
    args = parser.parse_args()

    mean = asyncio.run(_run(args.sample))

    if mean < _SCORE_GATE:
        print(f"\nFAIL — Overall mean {mean:.3f} is below the gate of {_SCORE_GATE}.")
        sys.exit(1)
    else:
        print(f"\nPASS — Overall mean {mean:.3f} meets the gate of {_SCORE_GATE}.")


if __name__ == "__main__":
    main()
