"""PII detection and masking via Microsoft Presidio.

Audit fix L6 (`docs/03_BACKEND_DESIGN.md`): v1's masker silently passed
through the original, unmasked text if Presidio itself failed. v2 never
ships unmasked PII — a failure during masking is logged at WARN and
re-raised as a typed `PIIMaskingError`, only when PII was actually detected
(if nothing was found, there's nothing that could leak, so a downstream
failure there would be a false escalation).

Presidio's `AnalyzerEngine` always needs an NLP engine to tokenize text —
even for the regex-based recognizers below — so a spaCy model
(`en_core_web_sm`) must be installed (`python -m spacy download
en_core_web_sm`) regardless of which entity types are targeted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

from src.core.exceptions import PIIMaskingError
from src.core.logging import get_logger

logger = get_logger(__name__)

# 8 entity types relevant to IT support tickets — see docs/03_BACKEND_DESIGN.md
# Phase 2 deliverables ("Presidio, 8 entity types").
ENTITY_TYPES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IP_ADDRESS",
    "CREDIT_CARD",
    "US_SSN",
    "LOCATION",
    "URL",
]

_NLP_CONFIGURATION = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}


@dataclass(frozen=True, slots=True)
class MaskResult:
    masked_text: str
    pii_detected: bool
    entity_types: list[str] = field(default_factory=list)


class PIIMasker:
    def __init__(self) -> None:
        nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIGURATION).create_engine()
        self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        self._anonymizer = AnonymizerEngine()

    def _mask_sync(self, text: str) -> MaskResult:
        results = self._analyzer.analyze(text=text, entities=ENTITY_TYPES, language="en")
        if not results:
            return MaskResult(masked_text=text, pii_detected=False, entity_types=[])

        entity_types = sorted({r.entity_type for r in results})
        try:
            anonymized = self._anonymizer.anonymize(text=text, analyzer_results=results)
        except Exception as exc:
            # PII was detected but masking itself failed — never fall back to
            # shipping the original, unmasked text (audit fix L6).
            logger.warning(
                "pii_masking_failed",
                entity_types=entity_types,
                error=str(exc),
            )
            raise PIIMaskingError(
                "PII was detected but could not be masked; refusing to proceed with "
                "unmasked text.",
                details=[{"entity_types": entity_types}],
            ) from exc

        return MaskResult(masked_text=anonymized.text, pii_detected=True, entity_types=entity_types)

    async def mask(self, text: str) -> MaskResult:
        # CPU-bound (spaCy NER + regex recognizers) — never block the event
        # loop (audit fix H1).
        return await asyncio.to_thread(self._mask_sync, text)
