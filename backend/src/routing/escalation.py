"""EscalationDetector — plain Python keyword/pattern rules, no LLM.

Runs after routing has decided ASSIGNED or AUTO_RESOLVED and may override to
ESCALATED when ticket content signals urgency beyond what the quality score
alone can detect (e.g., outage keywords in a MEDIUM-confidence ticket).
"""

from __future__ import annotations

import re

from src.core.logging import get_logger
from src.db.models import Ticket

logger = get_logger(__name__)

_OUTAGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(outage|down|unavailable|critical|sev[- ]?1|p0|breach|ransomware|data.?loss)\b",
        re.I,
    ),
    re.compile(r"\b(all users|entire (company|org|department)|production (is )?down)\b", re.I),
]

_HIGH_PRIORITY_THRESHOLD = 2  # priority 1 or 2


class EscalationDetector:
    """Detect tickets that warrant escalation regardless of routing decision."""

    def should_escalate(self, ticket: Ticket, escalation_reason_out: list[str]) -> bool:
        """Return True if content/priority signals demand escalation.

        Appends a human-readable reason to `escalation_reason_out` when True.
        """
        text = f"{ticket.title} {ticket.description}"

        for pattern in _OUTAGE_PATTERNS:
            match = pattern.search(text)
            if match:
                reason = f"Escalation keyword detected: '{match.group(0)}'"
                escalation_reason_out.append(reason)
                logger.info(
                    "escalation_keyword_detected",
                    ticket_id=str(ticket.id),
                    keyword=match.group(0),
                )
                return True

        if ticket.priority <= _HIGH_PRIORITY_THRESHOLD:
            reason = f"High priority ticket (priority={ticket.priority})"
            escalation_reason_out.append(reason)
            logger.info(
                "escalation_high_priority",
                ticket_id=str(ticket.id),
                priority=ticket.priority,
            )
            return True

        return False
