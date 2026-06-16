"""Train and save the LinearSVC ticket classifier.

Reads labeled data from the database (CSV-source tickets only — audit fix H3),
embeds with all-MiniLM-L6-v2, fits a CalibratedClassifierCV, and writes the
model to `data/models/classifier.pkl`.

Usage:
    python scripts/train_classifier.py
    python scripts/train_classifier.py --model-path data/models/classifier.pkl
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from src.classification import trainer
from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)


async def _run(model_path: Path) -> None:
    async with session_scope() as session:
        ticket_repo = TicketRepository(session)
        trained = await trainer.train(ticket_repo)

    trainer.save(trained, model_path)
    logger.info(
        "train_complete",
        model_path=str(model_path),
        training_samples=trained.training_samples,
        classes=[c.value for c in trained.classes],
    )


def main() -> None:
    configure_logging()
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path(settings.model_dir) / "classifier.pkl",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.model_path))


if __name__ == "__main__":
    main()
