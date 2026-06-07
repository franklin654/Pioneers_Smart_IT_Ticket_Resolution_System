"""Load the UCI Incident Management Process Enriched Event Log into the database.

The UCI dataset contains 141,712 events across 24,918 unique ServiceNow incidents.
This script handles its specific 36-column schema:
  - Filters to closed incidents only (``incident_state = 'Closed'``)
  - Deduplicates on ``sys_id`` — keeps the most recent row per incident
  - Maps ``urgency`` + ``impact`` (1=High, 2=Medium, 3=Low) to priority (1–5)
  - Maps ServiceNow ``category``/``subcategory`` labels to our 6 TicketCategory values
  - Uses ``close_notes`` as the resolution text for KB entries

Source: https://archive.ics.uci.edu/ml/datasets/Incident+management+process+enriched+event+log

Usage::

    # From the backend/ directory
    python -m scripts.load_uci_incidents --input-path data/raw/uci_incidents.csv
    python -m scripts.load_uci_incidents --input-path data/raw/uci_incidents.csv --batch-size 200

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
from src.db.models import (
    KnowledgeBaseEntry,
    Ticket,
    TicketCategory,
    TicketSource,
    TicketStatus,
)

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)

# UCI uses ServiceNow category names — supplement CATEGORY_MAPPING with UCI-specific variants
UCI_CATEGORY_EXTRAS: dict[str, TicketCategory] = {
    "hardware": TicketCategory.INFRASTRUCTURE,
    "software": TicketCategory.APPLICATION,
    "network": TicketCategory.NETWORK,
    "database": TicketCategory.DATABASE,
    "security": TicketCategory.SECURITY,
    "access": TicketCategory.ACCESS_MANAGEMENT,
    "end user": TicketCategory.APPLICATION,
    "end_user": TicketCategory.APPLICATION,
    "operating system": TicketCategory.INFRASTRUCTURE,
}

_FULL_CATEGORY_MAP = {**CATEGORY_MAPPING, **UCI_CATEGORY_EXTRAS}


def _uci_priority(urgency, impact) -> int:
    """Map ServiceNow urgency + impact (1=High, 2=Medium, 3=Low) to priority (1–5).

    Takes the more severe (lower) of the two signals and maps to our 1–5 scale.
    """
    try:
        combined = min(int(urgency), int(impact))
        return {1: 1, 2: 2, 3: 3}.get(combined, 3)
    except (ValueError, TypeError):
        return 3


def _map_uci_category(category: str, subcategory: str) -> TicketCategory | None:
    """Try category first, fall back to subcategory."""
    result = _FULL_CATEGORY_MAP.get(str(category).strip().lower())
    if result is None:
        result = _FULL_CATEGORY_MAP.get(str(subcategory).strip().lower())
    return result


@app.command()
def main(
    input_path: Path = typer.Option(..., "--input-path", "-i", help="Path to the UCI CSV file"),
    batch_size: int = typer.Option(200, "--batch-size", "-b", help="DB insertion batch size"),
) -> None:
    """Load UCI Incident Management data into the database."""
    asyncio.run(_load(input_path, batch_size))


async def _load(input_path: Path, batch_size: int) -> None:
    if not input_path.exists():
        logger.error("Input file not found", extra={"metadata": {"path": str(input_path)}})
        sys.exit(1)

    await init_db()

    df = pd.read_csv(input_path, low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    logger.info(
        "UCI CSV loaded",
        extra={"metadata": {"rows": len(df), "columns": list(df.columns[:10])}},
    )

    # ── Validate required columns exist ───────────────────────────────────
    required = {"sys_id", "incident_state", "short_description"}
    missing = required - set(df.columns)
    if missing:
        logger.error(
            "Required UCI columns missing",
            extra={"metadata": {"missing": list(missing), "found": list(df.columns)}},
        )
        sys.exit(1)

    # ── 1. Filter: closed incidents only ──────────────────────────────────
    df = df[df["incident_state"].astype(str).str.strip().str.lower() == "closed"]
    logger.info("After closed filter", extra={"metadata": {"rows": len(df)}})

    # ── 2. Deduplicate: one row per sys_id (most recent event) ────────────
    if "sys_updated_on" in df.columns:
        df = df.sort_values("sys_updated_on", ascending=True)
    df = df.drop_duplicates(subset=["sys_id"], keep="last")
    logger.info("After sys_id deduplication", extra={"metadata": {"unique_incidents": len(df)}})

    # ── 3. Select resolution column ───────────────────────────────────────
    res_col = next(
        (c for c in ["close_notes", "resolution_notes", "resolution"] if c in df.columns),
        None,
    )
    cat_col = "category" if "category" in df.columns else None
    sub_col = "subcategory" if "subcategory" in df.columns else None
    desc_col = next(
        (c for c in ["description", "details", "comments"] if c in df.columns),
        None,
    )

    inserted_tickets = 0
    inserted_kb = 0
    skipped = 0
    seen_hashes: set[str] = set()

    async with AsyncSessionLocal() as session:
        batch_tickets: list[Ticket] = []
        batch_kb: list[KnowledgeBaseEntry] = []

        for _, row in df.iterrows():
            title = str(row["short_description"]).strip()
            if not title or title.lower() in ("nan", "none", ""):
                skipped += 1
                continue

            description = str(row[desc_col]).strip() if desc_col and pd.notna(row.get(desc_col)) else title
            if not description or description.lower() in ("nan", "none"):
                description = title

            content_hash = _compute_hash(title, description)
            if content_hash in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(content_hash)

            raw_cat = str(row[cat_col]) if cat_col and pd.notna(row.get(cat_col)) else ""
            raw_sub = str(row[sub_col]) if sub_col and pd.notna(row.get(sub_col)) else ""
            category = _map_uci_category(raw_cat, raw_sub)

            priority = _uci_priority(
                row.get("urgency", 3),
                row.get("impact", 3),
            )

            batch_tickets.append(
                Ticket(
                    title=title,
                    description=description,
                    original_description=description,
                    category=category,
                    priority=priority,
                    status=TicketStatus.CLOSED,
                    content_hash=content_hash,
                    source=TicketSource.CSV,
                )
            )

            if res_col and pd.notna(row.get(res_col)) and category:
                resolution_text = str(row[res_col]).strip()
                if resolution_text and resolution_text.lower() not in ("nan", "none", ""):
                    batch_kb.append(
                        KnowledgeBaseEntry(
                            title=title,
                            description=description,
                            category=category,
                            resolution=resolution_text,
                            source="uci",
                        )
                    )

            if len(batch_tickets) >= batch_size:
                count = await _flush_batch(session, batch_tickets, batch_kb)
                inserted_tickets += count
                inserted_kb += len(batch_kb)
                batch_tickets.clear()
                batch_kb.clear()

        if batch_tickets:
            count = await _flush_batch(session, batch_tickets, batch_kb)
            inserted_tickets += count
            inserted_kb += len(batch_kb)

        await session.commit()

    logger.info(
        "UCI load complete",
        extra={"metadata": {
            "inserted_tickets": inserted_tickets,
            "inserted_kb_entries": inserted_kb,
            "skipped": skipped,
        }},
    )


if __name__ == "__main__":
    app()
