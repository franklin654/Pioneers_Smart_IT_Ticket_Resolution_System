"""Load a synthetic CSV (from `generate_synthetic_data.py`) into the database.

CSV-sourced tickets (`--ticket-source csv`, the default) become training data
*and* seed `knowledge_base_entries` when a non-empty `resolution` column is
present. WEBHOOK-sourced tickets (`--ticket-source webhook`) are the held-out
evaluation set used only by `routing_accuracy_eval.py` / `holdout_eval.py` —
never used for training, so accuracy numbers aren't inflated by leakage
(`docs/06_DATA_AND_EVALUATION.md`).

Usage:
    python scripts/load_tickets.py --input-path data/raw/synthetic_train.csv \\
        --source synthetic_train
    python scripts/load_tickets.py --input-path data/raw/synthetic_test.csv \\
        --source synthetic_test --ticket-source webhook
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path

from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.models import TicketCategory, TicketSource, TicketStatus
from src.db.repositories import KnowledgeBaseRepository, TicketRepository
from src.ingestion.deduplicator import compute_content_hash

logger = get_logger(__name__)

_COMMIT_BATCH_SIZE = 200
_DEFAULT_PRIORITY = 3


def _read_rows(input_path: Path) -> list[dict]:
    with input_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_priority(raw_value: str | None, row_number: int) -> int:
    """An optional `priority` column (1-5) may be present — fall back to the
    default if it's missing or out of range rather than rejecting the whole
    row over a non-essential field."""
    if raw_value is None or not raw_value.strip():
        return _DEFAULT_PRIORITY
    try:
        priority = int(raw_value.strip())
    except ValueError:
        logger.warning("invalid_priority_value", row=row_number, value=raw_value)
        return _DEFAULT_PRIORITY
    if not 1 <= priority <= 5:
        logger.warning("priority_out_of_range", row=row_number, value=priority)
        return _DEFAULT_PRIORITY
    return priority


async def load_tickets(input_path: Path, source_label: str, ticket_source: TicketSource) -> None:
    rows = _read_rows(input_path)
    loaded, duplicates, invalid, kb_created = 0, 0, 0, 0

    async with session_scope() as session:
        ticket_repo = TicketRepository(session)
        kb_repo = KnowledgeBaseRepository(session)

        for i, row in enumerate(rows, start=1):
            title = (row.get("title") or "").strip()
            description = (row.get("description") or "").strip()
            category_raw = (row.get("category") or "").strip().lower()
            resolution = (row.get("resolution") or "").strip()
            priority = _parse_priority(row.get("priority"), i)

            if not title or not description:
                invalid += 1
                continue
            try:
                category = TicketCategory(category_raw)
            except ValueError:
                logger.warning("skip_invalid_category", row=i, category=category_raw)
                invalid += 1
                continue

            content_hash = compute_content_hash(title, description)
            if await ticket_repo.get_by_content_hash(content_hash) is not None:
                duplicates += 1
                continue

            await ticket_repo.create(
                title=title,
                description=description,
                original_description=description,
                category=category,
                priority=priority,
                status=TicketStatus.CLOSED,  # historical labeled data, not a live pipeline item
                source=ticket_source,
                pii_detected=False,
                content_hash=content_hash,
            )
            loaded += 1

            if ticket_source == TicketSource.CSV and resolution:
                await kb_repo.create(
                    title=title,
                    description=description,
                    category=category,
                    resolution=resolution,
                    source=source_label,
                )
                kb_created += 1

            if i % _COMMIT_BATCH_SIZE == 0:
                await session.commit()
                logger.info("load_progress", processed=i, total=len(rows))

        await session.commit()

    logger.info(
        "load_complete",
        loaded=loaded,
        duplicates_skipped=duplicates,
        invalid_skipped=invalid,
        kb_entries_created=kb_created,
    )


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-path", type=Path, required=True)
    parser.add_argument(
        "--source", required=True, help="Free-text provenance label stored on KB entries."
    )
    parser.add_argument("--ticket-source", choices=["csv", "webhook"], default="csv")
    args = parser.parse_args()

    asyncio.run(load_tickets(args.input_path, args.source, TicketSource(args.ticket_source)))


if __name__ == "__main__":
    main()
