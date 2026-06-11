"""AutoGen UserProxyAgent representing the system interface.

Drives the conversation (initiates chats with domain agents), collects the
final EVALUATION_RESULT, and triggers the routing decision + Resolution
persistence.

``human_input_mode="NEVER"`` — this is a fully automated proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import autogen

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.routing.router import TicketRouter

logger = get_logger(__name__)


class TicketUserProxy(autogen.UserProxyAgent):
    """AutoGen UserProxyAgent that initiates and terminates the agent pipeline.

    The proxy sends the first CLASSIFY message and stops the conversation as
    soon as it receives an EVALUATION_RESULT (or an ERROR from any agent).
    Routing and persistence are handled by
    :class:`~src.agents.orchestrator.TicketOrchestrator` after the chat ends.

    Args:
        router: :class:`~src.routing.router.TicketRouter` for the final
            routing decision (passed through for access by the orchestrator).
    """

    def __init__(
        self,
        router: "TicketRouter",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="TicketUserProxy",
            human_input_mode="NEVER",
            is_termination_msg=self._is_terminal,
            code_execution_config=False,
            **kwargs,
        )
        self.router = router

    # ── Termination condition ──────────────────────────────────────────────────

    @staticmethod
    def _is_terminal(msg: dict) -> bool:
        """Stop the conversation when an EVALUATION_RESULT or ERROR arrives."""
        import json

        content = msg.get("content", "")
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            return parsed.get("type") in {"EVALUATION_RESULT", "ERROR"}
        except (json.JSONDecodeError, AttributeError):
            return False
