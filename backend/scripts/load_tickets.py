"""Load synthetic IT support ticket CSV files into the database.

Reads the CSV files produced by ``scripts/generate_synthetic_data.py`` and
inserts them into the ``tickets`` and ``knowledge_base_entries`` tables.

Two modes (matching the generator's ``--mode`` flag):

    **Training data** (``--mode train`` output) — has ``resolution`` column.
    Rows are inserted as ``TicketSource.CSV`` tickets and also into
    ``knowledge_base_entries`` so the RAG retriever can use them.

    **Held-out test data** (``--mode test`` output) — no ``resolution`` column.
    Pass ``--ticket-source webhook`` so the routing accuracy evaluator can
    query this set separately from training tickets.  No KB entries are created
    (no resolution column → nothing to index).

Typical usage::

    # Load training data
    python -m scripts.load_tickets \\
        --input-path data/raw/synthetic_train.csv \\
        --source synthetic_train

    # Load held-out test set
    python -m scripts.load_tickets \\
        --input-path data/raw/synthetic_test.csv \\
        --ticket-source webhook \\
        --source synthetic_test

Environment:
    DATABASE_URL: Required.  Loaded from .env or the process environment.
"""

import asyncio
import hashlib
import sys
from pathlib import Path

import pandas as pd
import typer

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

# Maps category label variants to canonical TicketCategory values.
# Synthetic CSVs use exact enum values, so the top entries always match.
# The synonyms below are kept for any future ad-hoc data loads.
CATEGORY_MAPPING: dict[str, TicketCategory] = {
    # ── Infrastructure ────────────────────────────────────────────────────────
    "infrastructure": TicketCategory.INFRASTRUCTURE,
    "infra": TicketCategory.INFRASTRUCTURE,
    "hardware": TicketCategory.INFRASTRUCTURE,
    "hardware support": TicketCategory.INFRASTRUCTURE,
    "server": TicketCategory.INFRASTRUCTURE,
    "os": TicketCategory.INFRASTRUCTURE,
    "systems": TicketCategory.INFRASTRUCTURE,
    "incident": TicketCategory.INFRASTRUCTURE,
    "service outages": TicketCategory.INFRASTRUCTURE,
    "service outages and maintenance": TicketCategory.INFRASTRUCTURE,
    "outage": TicketCategory.INFRASTRUCTURE,
    # ── Application ───────────────────────────────────────────────────────────
    "application": TicketCategory.APPLICATION,
    "app": TicketCategory.APPLICATION,
    "software": TicketCategory.APPLICATION,
    "software development": TicketCategory.APPLICATION,
    "service": TicketCategory.APPLICATION,
    "technical support": TicketCategory.APPLICATION,
    "technical_support": TicketCategory.APPLICATION,
    "it support": TicketCategory.APPLICATION,
    "helpdesk": TicketCategory.APPLICATION,
    "product support": TicketCategory.APPLICATION,
    "internal project": TicketCategory.APPLICATION,
    "purchase": TicketCategory.APPLICATION,
    # ── Security ──────────────────────────────────────────────────────────────
    "security": TicketCategory.SECURITY,
    "cybersecurity": TicketCategory.SECURITY,
    "vulnerability": TicketCategory.SECURITY,
    "information security": TicketCategory.SECURITY,
    # ── Database ──────────────────────────────────────────────────────────────
    "database": TicketCategory.DATABASE,
    "db": TicketCategory.DATABASE,
    "data": TicketCategory.DATABASE,
    "dba": TicketCategory.DATABASE,
    # ── Access Management ─────────────────────────────────────────────────────
    "access": TicketCategory.ACCESS_MANAGEMENT,
    "access management": TicketCategory.ACCESS_MANAGEMENT,
    "access_management": TicketCategory.ACCESS_MANAGEMENT,
    "account": TicketCategory.ACCESS_MANAGEMENT,
    "account access": TicketCategory.ACCESS_MANAGEMENT,
    "account_access": TicketCategory.ACCESS_MANAGEMENT,
    "storage": TicketCategory.ACCESS_MANAGEMENT,
    "identity": TicketCategory.ACCESS_MANAGEMENT,
    "iam": TicketCategory.ACCESS_MANAGEMENT,
    "user accounts": TicketCategory.ACCESS_MANAGEMENT,
    "user_accounts": TicketCategory.ACCESS_MANAGEMENT,
    "administrative rights": TicketCategory.ACCESS_MANAGEMENT,
    # ── Network ───────────────────────────────────────────────────────────────
    "network": TicketCategory.NETWORK,
    "networking": TicketCategory.NETWORK,
    "connectivity": TicketCategory.NETWORK,
    "network operations": TicketCategory.NETWORK,
    "network ops": TicketCategory.NETWORK,
}


def _detect_column(candidates: list[str], df_columns: list[str]) -> str | None:
    """Return the first df column whose lowercased name contains any candidate."""
    lower_cols = [c.lower() for c in df_columns]
    for candidate in candidates:
        for i, col in enumerate(lower_cols):
            if candidate in col:
                return df_columns[i]
    return None


def _map_category(raw: str) -> TicketCategory | None:
    """Map a category label to a TicketCategory enum value."""
    return CATEGORY_MAPPING.get(str(raw).strip().lower())


def _compute_hash(title: str, description: str) -> str:
    """SHA-256 hash of normalized title + description for exact deduplication."""
    normalized = f"{title.strip().lower()}::{description.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@app.command()
def main(
    input_path: Path = typer.Option(..., "--input-path", "-i", help="Path to CSV file"),
    batch_size: int = typer.Option(100, "--batch-size", "-b", help="DB insertion batch size"),
    source: str = typer.Option(
        "synthetic",
        "--source",
        "-s",
        help="Source tag written to KnowledgeBaseEntry.source for traceability.",
    ),
    categories: str = typer.Option(
        "",
        "--categories",
        help="Comma-separated canonical categories to include (e.g. 'infrastructure,security'). "
             "Default: all mapped categories.",
    ),
    max_per_category: int = typer.Option(
        0,
        "--max-per-category",
        help="Cap inserted tickets per category. 0 = unlimited.",
    ),
    ticket_source: str = typer.Option(
        "csv",
        "--ticket-source",
        help=(
            "TicketSource for inserted tickets: "
            "'csv' (training data, default) or "
            "'webhook' (held-out test set — isolated from training by routing_accuracy_eval.py)."
        ),
    ),
) -> None:
    """Load a synthetic ticket CSV into the database."""
    category_filter = {c.strip() for c in categories.split(",") if c.strip()} if categories else set()
    try:
        ts = TicketSource(ticket_source.lower())
    except ValueError:
        raise typer.BadParameter(f"Unknown ticket-source '{ticket_source}'. Use 'csv' or 'webhook'.")
    asyncio.run(_load(input_path, batch_size, source, category_filter, max_per_category, ts))


async def _load(
    input_path: Path,
    batch_size: int,
    source: str,
    category_filter: set[str] | None = None,
    max_per_category: int = 0,
    ticket_source: TicketSource = TicketSource.CSV,
) -> None:
    if not input_path.exists():
        logger.error("Input file not found", extra={"metadata": {"path": str(input_path)}})
        sys.exit(1)

    await init_db()

    suffix = input_path.suffix.lower()
    if suffix in (".parquet", ".pq"):
        df = pd.read_parquet(input_path)
    elif suffix == ".json":
        df = pd.read_json(input_path)
    elif suffix == ".jsonl":
        df = pd.read_json(input_path, lines=True)
    else:
        df = pd.read_csv(input_path)

    df.columns = [c.strip().lower() for c in df.columns]
    logger.info("File loaded", extra={"metadata": {"rows": len(df), "columns": list(df.columns)}})

    # ── Detect columns ─────────────────────────────────────────────────────
    title_col = _detect_column(
        ["short_description", "instruction", "title", "subject", "summary"],
        list(df.columns),
    )
    desc_col = _detect_column(
        ["complaint_what_happened", "body", "content", "description", "text", "detail", "document", "issue"],
        list(df.columns),
    )
    cat_col = _detect_column(
        ["queue", "assignment_group", "department", "category", "topic_group", "type", "class", "label", "group"],
        list(df.columns),
    )
    prio_col = _detect_column(["priority", "prio", "severity", "urgency"], list(df.columns))
    res_col = _detect_column(["resolution", "solution", "response", "answer", "fix", "resolve"], list(df.columns))

    if not desc_col:
        logger.error(
            "Cannot infer description column",
            extra={"metadata": {"columns": list(df.columns)}},
        )
        sys.exit(1)

    if not title_col:
        title_col = desc_col
        logger.info(
            "No title column found — using description column as title (truncated to 150 chars)",
            extra={"metadata": {"desc_col": desc_col}},
        )

    logger.info(
        "Column mapping resolved",
        extra={"metadata": {
            "title": title_col, "description": desc_col,
            "category": cat_col, "priority": prio_col, "resolution": res_col,
            "ticket_source": ticket_source.value,
        }},
    )

    df = df.dropna(subset=[title_col, desc_col])
    df[title_col] = df[title_col].astype(str).str.strip()
    df[desc_col] = df[desc_col].astype(str).str.strip()
    logger.info("After null drop", extra={"metadata": {"rows": len(df)}})

    inserted_tickets = 0
    inserted_kb = 0
    skipped = 0
    seen_hashes: set[str] = set()
    category_counts: dict[str, int] = {}

    if category_filter:
        logger.info(
            "Category filter active",
            extra={"metadata": {"allowed": sorted(category_filter), "max_per_category": max_per_category or "unlimited"}},
        )

    async with AsyncSessionLocal() as session:
        batch_tickets: list[Ticket] = []
        batch_kb: list[KnowledgeBaseEntry] = []

        for _, row in df.iterrows():
            description = str(row[desc_col])
            raw_title = str(row[title_col])
            title = raw_title[:150] if title_col == desc_col else raw_title
            content_hash = _compute_hash(title, description)

            if content_hash in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(content_hash)

            raw_cat = str(row[cat_col]) if cat_col and pd.notna(row.get(cat_col, None)) else ""
            category = _map_category(raw_cat) if raw_cat else None

            if category_filter and (category is None or category.value not in category_filter):
                skipped += 1
                continue

            if max_per_category and category is not None:
                count_so_far = category_counts.get(category.value, 0)
                if count_so_far >= max_per_category:
                    skipped += 1
                    continue
                category_counts[category.value] = count_so_far + 1

            try:
                raw_prio = row.get(prio_col) if prio_col else None
                if pd.isna(raw_prio):
                    priority = 3
                else:
                    _TEXT_PRIO = {"critical": 1, "high": 1, "medium": 2, "low": 3, "minimal": 4}
                    prio_str = str(raw_prio).strip().lower()
                    priority = _TEXT_PRIO.get(prio_str, max(1, min(5, int(raw_prio))))
            except (ValueError, TypeError):
                priority = 3

            batch_tickets.append(
                Ticket(
                    title=title,
                    description=description,
                    original_description=description,
                    category=category,
                    priority=priority,
                    status=TicketStatus.CLOSED,
                    content_hash=content_hash,
                    source=ticket_source,
                )
            )

            # Only insert KB entries for training data that has resolutions.
            # Test-set rows have no resolution column so res_col is None here.
            if res_col and pd.notna(row.get(res_col, None)) and category:
                resolution_text = str(row[res_col]).strip()
                if resolution_text:
                    batch_kb.append(
                        KnowledgeBaseEntry(
                            title=title,
                            description=description,
                            category=category,
                            resolution=resolution_text,
                            source=source,
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
        "Load complete",
        extra={"metadata": {
            "inserted_tickets": inserted_tickets,
            "inserted_kb_entries": inserted_kb,
            "skipped_duplicates": skipped,
            "source": source,
            "ticket_source": ticket_source.value,
        }},
    )


async def _flush_batch(
    session,
    tickets: list[Ticket],
    kb_entries: list[KnowledgeBaseEntry],
) -> int:
    """Flush a batch of tickets and KB entries; skip entire batch on error."""
    try:
        session.add_all(tickets)
        session.add_all(kb_entries)
        await session.flush()
        return len(tickets)
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Batch flush failed — skipping batch",
            extra={"metadata": {"error": str(exc), "batch_size": len(tickets)}},
        )
        return 0


if __name__ == "__main__":
    app()
