"""ClassifierAgent — thin ConversableAgent wrapper around TicketClassifier.

No `register_reply` / `_handle_*` dead code (audit fix C1).
The orchestrator calls `_classify()` directly.
"""

from __future__ import annotations

from autogen import ConversableAgent

from src.classification.classifier import ClassificationOutput, TicketClassifier


class ClassifierAgent(ConversableAgent):
    def __init__(self, classifier: TicketClassifier) -> None:
        super().__init__(
            name="ClassifierAgent",
            human_input_mode="NEVER",
            llm_config=False,
        )
        self._classifier = classifier

    async def _classify(self, title: str, description: str) -> ClassificationOutput:
        return await self._classifier.classify(title, description)
