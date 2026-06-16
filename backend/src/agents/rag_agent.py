"""RAGAgent — thin ConversableAgent wrapper around the retrieval + generation pipeline.

No `register_reply` / `_handle_*` dead code (audit fix C1).
The orchestrator calls `_run_rag()` directly.
"""

from __future__ import annotations

from autogen import ConversableAgent

from src.db.models import KnowledgeBaseEntry, ResolutionStep, TicketCategory
from src.rag.generator import GeneratorProtocol
from src.rag.reranker import MMRReranker
from src.rag.retriever import HybridRetriever


class RAGAgent(ConversableAgent):
    def __init__(
        self,
        retriever: HybridRetriever,
        reranker: MMRReranker,
        generator: GeneratorProtocol,
    ) -> None:
        super().__init__(
            name="RAGAgent",
            human_input_mode="NEVER",
            llm_config=False,
        )
        self._retriever = retriever
        self._reranker = reranker
        self._generator = generator

    async def _run_rag(
        self,
        title: str,
        description: str,
        category: TicketCategory,
    ) -> tuple[list[ResolutionStep], list[KnowledgeBaseEntry]]:
        """Retrieve → rerank → generate. Returns (steps, retrieved_entries)."""
        query = f"{title} {description}"
        candidates = await self._retriever.retrieve(query, category_filter=category)
        context = await self._reranker.rerank(query, candidates)
        steps = await self._generator.generate(title, description, category, context)
        return steps, context
