"""Ticket ingestion: validation, PII masking, deduplication."""

from src.ingestion.deduplicator import DedupCheckResult, Deduplicator, compute_content_hash
from src.ingestion.pii_masker import ENTITY_TYPES, MaskResult, PIIMasker
from src.ingestion.pipeline import IngestionPipeline, IngestionResult, build_ingestion_pipeline
from src.ingestion.validator import TicketValidator, ValidatedTicketText

__all__ = [
    "ENTITY_TYPES",
    "DedupCheckResult",
    "Deduplicator",
    "IngestionPipeline",
    "IngestionResult",
    "MaskResult",
    "PIIMasker",
    "TicketValidator",
    "ValidatedTicketText",
    "build_ingestion_pipeline",
    "compute_content_hash",
]
