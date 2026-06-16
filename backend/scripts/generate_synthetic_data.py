"""Generate a labeled synthetic ticket corpus via the Claude API.

Canonical data source for v2 — no Kaggle/UCI loader exists at all
(`docs/06_DATA_AND_EVALUATION.md`). Two modes:

  --mode train   Mostly clear-cut tickets across all 6 categories, each with a
                  `resolution` (used to seed knowledge_base_entries by
                  load_tickets.py), plus a deliberate ~30% slice of
                  ambiguous/multi-domain-flavored tickets so the classifier's
                  confidence distribution exercises the AWAITING_REVIEW gate
                  in evaluation, not just in production.
  --mode test    Harder, more ambiguous tickets, no `resolution` column —
                  loaded as the held-out WEBHOOK-source set, never used in
                  training (routing-accuracy / holdout evaluators only).

This script always calls the Claude API directly, independent of the
runtime LLM_PROVIDER setting — Claude is the canonical generator for the
corpus regardless of whether the deployed pipeline answers tickets with
Ollama or Claude.

Usage:
    python scripts/generate_synthetic_data.py --mode train --count 1200 \\
        --output data/raw/synthetic_train.csv
    python scripts/generate_synthetic_data.py --mode test --count 300 \\
        --output data/raw/synthetic_test.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Literal

import anthropic

from src.core.logging import configure_logging, get_logger
from src.db.models import TicketCategory

logger = get_logger(__name__)

_GENERATION_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS_PER_BATCH = 8192
_CSV_FIELDS = ["title", "description", "category", "resolution", "priority"]

_CATEGORY_BRIEFS = {
    TicketCategory.INFRASTRUCTURE: "servers, VMs, storage, hardware health, resource utilisation",
    TicketCategory.APPLICATION: "application errors, log analysis, environment/config differences",
    TicketCategory.SECURITY: (
        "incidents, suspicious activity, containment/investigation/remediation"
    ),
    TicketCategory.DATABASE: "PostgreSQL/MySQL/MSSQL performance, locks, replication, backups",
    TicketCategory.ACCESS_MANAGEMENT: "identity, permissions, SSO, least-privilege access requests",
    TicketCategory.NETWORK: "connectivity, latency, DNS, VPN, firewall, layered troubleshooting",
}


def _build_prompt(mode: Literal["train", "test"], batch_size: int) -> str:
    categories = ", ".join(c.value for c in TicketCategory)
    ambiguity_clause = (
        "About 70% of tickets should be clear-cut, unambiguously belonging to one "
        "category. About 30% should be deliberately ambiguous or touch two "
        "categories at once (e.g. a network issue that's actually a misconfigured "
        "access policy) so a classifier's confidence is genuinely tested."
        if mode == "train"
        else "Make these tickets harder than average: vague titles, terse or "
        "jargon-light descriptions, and a meaningful share that plausibly span "
        "two categories. This is a held-out evaluation set meant to stress-test "
        "the classifier and routing logic, not a training set."
    )
    resolution_clause = (
        'Include a "resolution" field: 3-6 concrete, numbered diagnostic/fix '
        "steps an IT support engineer would actually take, written as a single "
        "string with steps separated by newlines."
        if mode == "train"
        else (
            'Set "resolution" to an empty string "" for every ticket — '
            "this set has no ground-truth resolution."
        )
    )

    return f"""You are generating a synthetic IT support ticket dataset for an ML
classifier and RAG evaluation benchmark. Generate exactly {batch_size} distinct
tickets distributed roughly evenly across these categories: {categories}.

Category guidance:
{chr(10).join(f"- {cat.value}: {brief}" for cat, brief in _CATEGORY_BRIEFS.items())}

{ambiguity_clause}
{resolution_clause}

Respond with ONLY a JSON array (no markdown fences, no commentary) of objects
shaped exactly like:
{{"title": "...", "description": "...", "category": "<one of: {categories}>", \
"resolution": "...", "priority": <1-5>}}

Titles must be short (under 80 chars). Descriptions should read like a real
end user or junior engineer wrote them — 1-4 sentences, varied tone and detail
level. Every "category" value must be exactly one of the allowed values.
"priority" is an integer 1 (critical, widespread outage) to 5 (low,
cosmetic/non-urgent) reflecting the ticket's actual business impact and
urgency as described."""


def _extract_json_array(raw_text: str) -> list[dict]:
    """Claude is asked for raw JSON but may still wrap it in a code fence —
    fall back to extracting the first top-level array if direct parsing fails."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


_DEFAULT_PRIORITY = 3


def _coerce_priority(raw_value: object) -> int:
    try:
        priority = int(raw_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_PRIORITY
    return priority if 1 <= priority <= 5 else _DEFAULT_PRIORITY


def _validate_row(row: dict, mode: Literal["train", "test"]) -> dict | None:
    title = str(row.get("title", "")).strip()
    description = str(row.get("description", "")).strip()
    category_raw = str(row.get("category", "")).strip().lower()
    resolution = str(row.get("resolution", "")).strip()
    priority = _coerce_priority(row.get("priority"))

    if not title or not description:
        return None
    try:
        category = TicketCategory(category_raw)
    except ValueError:
        logger.warning("dropped_row_invalid_category", category=category_raw)
        return None
    if mode == "train" and not resolution:
        logger.warning("dropped_row_missing_resolution", title=title)
        return None

    return {
        "title": title,
        "description": description,
        "category": category.value,
        "resolution": resolution,
        "priority": priority,
    }


def generate_batch(
    client: anthropic.Anthropic, mode: Literal["train", "test"], batch_size: int
) -> list[dict]:
    response = client.messages.create(
        model=_GENERATION_MODEL,
        max_tokens=_MAX_TOKENS_PER_BATCH,
        messages=[{"role": "user", "content": _build_prompt(mode, batch_size)}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")
    rows = _extract_json_array(raw_text)

    validated = [v for row in rows if (v := _validate_row(row, mode)) is not None]
    logger.info("batch_generated", requested=batch_size, returned=len(rows), valid=len(validated))
    return validated


def generate_dataset(
    mode: Literal["train", "test"], count: int, batch_size: int = 25
) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY must be set to run synthetic data generation, "
            "independent of the runtime LLM_PROVIDER setting."
        )
    client = anthropic.Anthropic(api_key=api_key)

    rows: list[dict] = []
    while len(rows) < count:
        remaining = count - len(rows)
        rows.extend(generate_batch(client, mode, min(batch_size, remaining)))
    return rows[:count]


def write_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("csv_written", path=str(output_path), rows=len(rows))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["train", "test"], required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()

    rows = generate_dataset(args.mode, args.count, args.batch_size)
    write_csv(rows, args.output)


if __name__ == "__main__":
    main()
