"""Stage 1 of the ingestion pipeline: validation and sanitization.

Validates all field constraints on raw ticket input and sanitizes text
before any PII masking or ML processing. Operates entirely on plain Python
types — no database or model dependencies.
"""

import re
from typing import TYPE_CHECKING

from src.core.exceptions import ValidationError
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.ingestion.pipeline import IngestionContext

logger = get_logger(__name__)

# Compiled once at module load for performance
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_NULL_BYTE_RE = re.compile(r"\x00")


class TicketValidator:
    """Validates and sanitizes raw ticket input fields.

    Sanitization is applied before constraint checks so that length limits
    are evaluated on the final stored value, not the raw user input.

    Sanitization rules (applied in order):
        1. Strip null bytes
        2. Strip HTML / XML tags
        3. Collapse internal whitespace runs to single spaces
        4. Strip leading/trailing whitespace

    Constraint checks (applied after sanitization):
        - title: 3–200 characters
        - description: 10–5000 characters
        - priority: integer in [1, 5]

    Raises:
        ValidationError: On any constraint violation; ``detail["field"]``
            names the offending field and ``detail["value"]`` carries the
            sanitized value that failed.
    """

    TITLE_MIN: int = 3
    TITLE_MAX: int = 200
    DESC_MIN: int = 10
    DESC_MAX: int = 5000
    PRIORITY_MIN: int = 1
    PRIORITY_MAX: int = 5

    def validate(self, ctx: "IngestionContext") -> "IngestionContext":
        """Run all sanitization and validation steps.

        Args:
            ctx: Ingestion context with ``raw_title``, ``raw_description``,
                and ``priority`` populated.

        Returns:
            The same context instance with ``clean_title`` and
            ``clean_description`` populated.

        Raises:
            ValidationError: If any field fails its constraint.
        """
        ctx.clean_title = self._validate_text_field(
            raw=ctx.raw_title,
            field_name="title",
            min_len=self.TITLE_MIN,
            max_len=self.TITLE_MAX,
        )
        ctx.clean_description = self._validate_text_field(
            raw=ctx.raw_description,
            field_name="description",
            min_len=self.DESC_MIN,
            max_len=self.DESC_MAX,
        )
        self._validate_priority(ctx.priority)

        logger.info(
            "Ticket validated",
            extra={
                "metadata": {
                    "title_len": len(ctx.clean_title),
                    "desc_len": len(ctx.clean_description),
                    "priority": ctx.priority,
                }
            },
        )
        return ctx

    # ── Private helpers ───────────────────────────────────────────────────

    def _validate_text_field(
        self,
        raw: str,
        field_name: str,
        min_len: int,
        max_len: int,
    ) -> str:
        """Sanitize a text field and enforce length constraints.

        Args:
            raw: Raw user-supplied string.
            field_name: Name used in ValidationError detail.
            min_len: Minimum character length after sanitization.
            max_len: Maximum character length after sanitization.

        Returns:
            Sanitized string.

        Raises:
            ValidationError: If the sanitized string violates length constraints.
        """
        clean = self._sanitize_text(raw)

        if len(clean) < min_len:
            raise ValidationError(
                message=f"'{field_name}' must be at least {min_len} characters after sanitization",
                detail={"field": field_name, "min_length": min_len, "actual_length": len(clean)},
            )
        if len(clean) > max_len:
            raise ValidationError(
                message=f"'{field_name}' must not exceed {max_len} characters",
                detail={"field": field_name, "max_length": max_len, "actual_length": len(clean)},
            )
        return clean

    def _validate_priority(self, priority: int) -> None:
        """Validate that priority is an integer in [1, 5].

        Args:
            priority: Raw priority value from the request.

        Raises:
            ValidationError: If priority is outside [1, 5] or not an integer.
        """
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ValidationError(
                message="'priority' must be an integer",
                detail={"field": "priority", "value": priority},
            )
        if not (self.PRIORITY_MIN <= priority <= self.PRIORITY_MAX):
            raise ValidationError(
                message=f"'priority' must be between {self.PRIORITY_MIN} and {self.PRIORITY_MAX}",
                detail={
                    "field": "priority",
                    "value": priority,
                    "min": self.PRIORITY_MIN,
                    "max": self.PRIORITY_MAX,
                },
            )

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Apply all sanitization rules to a text string.

        Steps:
            1. Remove null bytes
            2. Strip HTML / XML tags
            3. Collapse whitespace runs to single spaces
            4. Strip leading/trailing whitespace

        Args:
            text: Raw input string.

        Returns:
            Sanitized string.
        """
        # Remove null bytes
        text = _NULL_BYTE_RE.sub("", text)
        # Strip HTML/XML tags
        text = _HTML_TAG_RE.sub("", text)
        # Normalize whitespace
        text = " ".join(text.split())
        return text

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML/XML tags from text.

        Uses a simple regex rather than an HTML parser to avoid adding
        a parser dependency.  Safe for the ticket text domain — we only
        need to strip tags, not parse document structure.

        Args:
            text: String potentially containing HTML tags.

        Returns:
            String with all tags removed.
        """
        return _HTML_TAG_RE.sub("", text)
