"""Stage 2 of the ingestion pipeline: PII detection and masking.

Uses Microsoft Presidio to detect and replace personally identifiable
information in ticket descriptions before persistence. The original text
is preserved on the Ticket model for auditing; only the masked text is
used for all downstream ML operations.

Lazy initialization pattern: Presidio's AnalyzerEngine loads a spaCy NLP
model on first use, which takes ~2–3 seconds. By deferring that load to
the first call to ``mask()``, application startup remains fast.
"""

from typing import TYPE_CHECKING

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.ingestion.pipeline import IngestionContext

logger = get_logger(__name__)


class PIIMasker:
    """Detects and masks PII in ticket descriptions using Microsoft Presidio.

    Supported entity types (8):
        - PERSON
        - EMAIL_ADDRESS
        - PHONE_NUMBER
        - US_SSN
        - CREDIT_CARD
        - IP_ADDRESS
        - DATE_TIME
        - LOCATION

    Masking strategy: Each detected entity is replaced with a bracketed
    type tag, e.g. ``<EMAIL_ADDRESS>``, ``<PHONE_NUMBER>``. This preserves
    the structure and approximate length of the text while removing
    identifying information.

    Resilience: Any exception raised by Presidio is caught and logged.
    The masker falls back to returning the original text with
    ``pii_detected=False``, so a Presidio failure never blocks ingestion.

    Note: The ticket title is intentionally NOT masked. Titles are short
    (≤200 chars), rarely contain extractable PII, and serve as a human-
    readable display key throughout the system.
    """

    SUPPORTED_ENTITIES: list[str] = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "IP_ADDRESS",
        "DATE_TIME",
        "LOCATION",
    ]

    def __init__(self) -> None:
        # Both engines are None until the first call to mask()
        self._analyzer = None
        self._anonymizer = None

    def mask(self, ctx: "IngestionContext") -> "IngestionContext":
        """Detect and mask PII in ``ctx.clean_description``.

        Populates:
            - ``ctx.masked_description``: Description with PII replaced.
            - ``ctx.pii_detected``: True if at least one entity was found.
            - ``ctx.pii_entity_types``: List of detected entity type strings.

        On Presidio failure the context is returned with ``masked_description``
        set to the original clean description and ``pii_detected=False``.

        Args:
            ctx: Ingestion context with ``clean_description`` populated.

        Returns:
            Updated context (never raises).
        """
        if not ctx.clean_description:
            ctx.masked_description = ctx.clean_description or ""
            return ctx

        try:
            analyzer = self._get_analyzer()
            anonymizer = self._get_anonymizer()

            results = analyzer.analyze(
                text=ctx.clean_description,
                entities=self.SUPPORTED_ENTITIES,
                language="en",
            )

            if not results:
                ctx.masked_description = ctx.clean_description
                ctx.pii_detected = False
                ctx.pii_entity_types = []
                return ctx

            # Build per-entity operator config
            operators = self._build_operator_config()

            from presidio_anonymizer.entities import OperatorConfig
            anonymized = anonymizer.anonymize(
                text=ctx.clean_description,
                analyzer_results=results,
                operators=operators,
            )

            detected_types = sorted({r.entity_type for r in results})
            ctx.masked_description = anonymized.text
            ctx.pii_detected = True
            ctx.pii_entity_types = detected_types

            logger.info(
                "PII masked",
                extra={"metadata": {"entity_types": detected_types, "count": len(results)}},
            )

        except Exception as exc:
            logger.warning(
                "PII masking failed — using original text",
                extra={"metadata": {"error": str(exc)}},
            )
            ctx.masked_description = ctx.clean_description
            ctx.pii_detected = False
            ctx.pii_entity_types = []

        return ctx

    # ── Private helpers ───────────────────────────────────────────────────

    def _get_analyzer(self):
        """Lazy-initialize and return the Presidio AnalyzerEngine.

        The analyzer loads the ``en_core_web_lg`` spaCy model on first call.
        Subsequent calls return the cached instance immediately.
        """
        if self._analyzer is None:
            from presidio_analyzer import AnalyzerEngine
            self._analyzer = AnalyzerEngine()
        return self._analyzer

    def _get_anonymizer(self):
        """Lazy-initialize and return the Presidio AnonymizerEngine."""
        if self._anonymizer is None:
            from presidio_anonymizer import AnonymizerEngine
            self._anonymizer = AnonymizerEngine()
        return self._anonymizer

    def _build_operator_config(self) -> dict:
        """Build a per-entity-type operator config for the anonymizer.

        Each entity type is configured to use the ``replace`` operator
        with a ``<ENTITY_TYPE>`` placeholder so the replacement is
        self-documenting in the masked text.

        Returns:
            Dict mapping entity type string → ``OperatorConfig(replace)``.
        """
        from presidio_anonymizer.entities import OperatorConfig

        return {
            entity: OperatorConfig("replace", {"new_value": f"<{entity}>"})
            for entity in self.SUPPORTED_ENTITIES
        }
