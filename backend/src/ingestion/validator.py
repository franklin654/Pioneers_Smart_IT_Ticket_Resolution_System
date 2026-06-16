"""Sanitizes and re-validates ticket text beyond what Pydantic's declarative
field constraints (`schemas/ticket.py`) already cover at the HTTP boundary.

Two things Pydantic's `min_length`/`max_length` cannot catch on their own:

1. A whitespace-only string (`"   "`) passes `min_length=1` but is empty once
   stripped — would otherwise persist a blank ticket.
2. Postgres `text` columns reject NUL bytes (`\\x00`) outright with a DB error;
   stripping them here turns a confusing 500 into a clean validation failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.exceptions import ValidationError

# Strip ASCII control characters (including NUL) but keep tab/newline/CR,
# which are legitimate in a multi-line ticket description.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class ValidatedTicketText:
    clean_title: str
    clean_description: str


def _sanitize(text: str) -> str:
    return _CONTROL_CHARS.sub("", text).strip()


class TicketValidator:
    def validate(self, title: str, description: str) -> ValidatedTicketText:
        clean_title = _sanitize(title)
        clean_description = _sanitize(description)

        if not clean_title:
            raise ValidationError("Title must not be empty or whitespace-only.", field="title")
        if not clean_description:
            raise ValidationError(
                "Description must not be empty or whitespace-only.", field="description"
            )

        return ValidatedTicketText(clean_title=clean_title, clean_description=clean_description)
