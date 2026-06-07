"""Load the 6StringNinja ServiceNow dataset as a held-out routing accuracy test set.

This script loads 500 synthetic ServiceNow incidents for use as a held-out
evaluation set — NOT training data.  All rows are tagged with
``source = "servicenow_test"`` so the routing accuracy evaluator can query
them separately from training tickets.

Key constraints:
  - Rows are NEVER inserted into ``knowledge_base_entries``
  - ``ticket.category`` is set from the ``assignment_group`` field (ground truth)
  - ``ticket.status = CLOSED`` — these are pre-resolved reference incidents
  - The source tag ``"servicenow_test"`` must remain consistent with
    ``evaluation/routing_accuracy_eval.py``

Source: https://huggingface.co/datasets/6StringNinja/synthetic-servicenow-incidents

Usage::

    # From the backend/ directory
    python -m scripts.load_servicenow_test_set --input-path data/raw/servicenow_test.parquet

Environment:
    DATABASE_URL: Required.  Loaded from .env or the process environment.
"""

import asyncio
import sys
from pathlib import Path

import pandas as pd
import typer

from scripts.load_kaggle_data import CATEGORY_MAPPING, _compute_hash, _flush_batch
from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, init_db
from src.db.models import Ticket, TicketCategory, TicketSource, TicketStatus

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)

# ServiceNow assignment group names → our categories
_ASSIGNMENT_GROUP_MAP = {
    **CATEGORY_MAPPING,
    # ServiceNow-specific group names that may appear in this dataset
    "network team": "network",
    "network operations": "network",
    "network ops": "network",
    "it support": "application",
    "server team": "infrastructure",
    "infrastructure team": "infrastructure",
    "security team": "security",
    "information security": "security",
    "database team": "database",
    "dba team": "database",
    "application team": "application",
    "app support": "application",
    "help desk": "application",
    "service desk": "application",
    "iam team": "access_management",
    "identity team": "access_management",
    "access management": "access_management",
}

_SOURCE_TAG = "servicenow_test"


def _map_assignment_group(raw: str):
    """Map assignment_group to TicketCategory via CATEGORY_MAPPING."""
    key = str(raw).strip().lower()
    result = _ASSIGNMENT_GROUP_MAP.get(key)
    if result is None:
        return None
    if isinstance(result, str):
        try:
            return TicketCategory(result)
        except ValueError:
            return None
    return result


@app.command()
def main(
    input_path: Path = typer.Option(
        ..., "--input-path", "-i",
        help="Path to the 6StringNinja Parquet file (or CSV)",
    ),
) -> None:
    """Load ServiceNow test set (held-out, not for training) into the database."""
    asyncio.run(_load(input_path))


async def _load(input_path: Path) -> None:
    if not input_path.exists():
        logger.error("Input file not found", extra={"metadata": {"path": str(input_path)}})
        sys.exit(1)

    await init_db()

    suffix = input_path.suffix.lower()
    if suffix in (".parquet", ".pq"):
        df = pd.read_parquet(input_path)
    else:
        df = pd.read_csv(input_path)

    df.columns = [c.strip().lower() for c in df.columns]
    logger.info(
        "ServiceNow test set loaded",
        extra={"metadata": {"rows": len(df), "columns": list(df.columns)}},
    )

    # ── Column detection ───────────────────────────────────────────────────
    # ServiceNow schema: short_description, description, assignment_group, urgency
    title_col = next(
        (c for c in ["short_description", "title", "subject", "summary"] if c in df.columns),
        None,
    )
    desc_col = next(
        (c for c in ["description", "body", "details", "text"] if c in df.columns),
        None,
    )
    # Prefer the per-ticket 'category' column (Software/Access/Hardware/Network)
    # over 'assignment_group' (IT Support/Network Ops) — it gives 4 distinct
    # labels that map cleanly to our taxonomy instead of just 2.
    group_col = next(
        (c for c in ["category", "assignment_group", "queue", "team", "group"] if c in df.columns),
        None,
    )
    prio_col = next(
        (c for c in ["urgency", "priority", "severity"] if c in df.columns),
        None,
    )

    if not title_col:
        logger.error(
            "Cannot find title column",
            extra={"metadata": {"columns": list(df.columns)}},
        )
        sys.exit(1)

    logger.info(
        "Column mapping",
        extra={"metadata": {
            "title": title_col, "description": desc_col,
            "assignment_group": group_col, "priority": prio_col,
        }},
    )

    df = df.dropna(subset=[title_col])
    df[title_col] = df[title_col].astype(str).str.strip()

    inserted = 0
    skipped = 0
    no_category = 0
    seen_hashes: set[str] = set()

    async with AsyncSessionLocal() as session:
        batch: list[Ticket] = []

        for _, row in df.iterrows():
            title = str(row[title_col])
            if not title or title.lower() in ("nan", "none", ""):
                skipped += 1
                continue

            description = (
                str(row[desc_col]).strip()
                if desc_col and pd.notna(row.get(desc_col))
                else title
            )
            if not description or description.lower() in ("nan", "none"):
                description = title

            content_hash = _compute_hash(title, description)
            if content_hash in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(content_hash)

            raw_group = str(row[group_col]) if group_col and pd.notna(row.get(group_col)) else ""
            category = _map_assignment_group(raw_group) if raw_group else None
            if category is None:
                no_category += 1

            try:
                raw_prio = row.get(prio_col) if prio_col else None
                # ServiceNow urgency: 1=High, 2=Medium, 3=Low — invert to our 1–5 scale
                prio_int = int(raw_prio) if pd.notna(raw_prio) else 3
                priority = {1: 1, 2: 2, 3: 3}.get(prio_int, 3)
            except (ValueError, TypeError):
                priority = 3

            batch.append(
                Ticket(
                    title=title,
                    description=description,
                    original_description=description,
                    category=category,
                    priority=priority,
                    status=TicketStatus.CLOSED,
                    content_hash=content_hash,
                    source=TicketSource.WEBHOOK,
                )
            )

            if len(batch) >= 100:
                count = await _flush_batch(session, batch, [])
                inserted += count
                batch.clear()

        if batch:
            count = await _flush_batch(session, batch, [])
            inserted += count

        await session.commit()

    logger.info(
        "ServiceNow test set load complete",
        extra={"metadata": {
            "inserted": inserted,
            "skipped_duplicates": skipped,
            "no_category_mapping": no_category,
            "source_tag": _SOURCE_TAG,
        }},
    )
    if no_category > 0:
        logger.warning(
            "Some tickets have no category — assignment_group values not in mapping. "
            "Add them to _ASSIGNMENT_GROUP_MAP if needed.",
            extra={"metadata": {"count": no_category}},
        )


if __name__ == "__main__":
    app()
