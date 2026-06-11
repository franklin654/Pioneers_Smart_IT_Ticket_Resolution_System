"""AutoGen agent running the full RAG pipeline for a classified ticket.

Receives a RETRIEVE_AND_GENERATE message, runs hybrid retrieval → MMR
reranking → LLM generation, and returns a RESOLUTION_GENERATED message.
Status transitions: ``CLASSIFIED → RETRIEVING → GENERATING``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import autogen

from src.core.exceptions import LLMUnavailableError, RAGRetrievalError
from src.core.logging import get_logger
from src.db.models import TicketCategory, TicketStatus

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
    from src.db.repositories.ticket_repo import TicketRepository
    from src.embedding.generator import EmbeddingGenerator
    from src.rag.generator import RAGGenerator
    from src.rag.knowledge_base import KnowledgeBase
    from src.rag.reranker import MMRReranker
    from src.rag.retriever import HybridRetriever

logger = get_logger(__name__)


class RAGAgent(autogen.ConversableAgent):
    """AutoGen agent that retrieves context and generates a resolution.

    Wraps :class:`~src.rag.retriever.HybridRetriever`,
    :class:`~src.rag.reranker.MMRReranker`, and
    :class:`~src.rag.generator.RAGGenerator` into a single pipeline step.

    Args:
        kb: :class:`~src.rag.knowledge_base.KnowledgeBase` with BM25 index
            already built at startup.
        kb_repo: For dense vector search.
        retriever: :class:`~src.rag.retriever.HybridRetriever` instance.
        reranker: :class:`~src.rag.reranker.MMRReranker` instance.
        rag_generator: :class:`~src.rag.generator.RAGGenerator` instance.
        embedding_generator: For building the query vector.
        ticket_repo: For status updates.
        settings: Application settings.
    """

    def __init__(
        self,
        kb: "KnowledgeBase",
        kb_repo: "KnowledgeBaseRepository",
        retriever: "HybridRetriever",
        reranker: "MMRReranker",
        rag_generator: "RAGGenerator",
        embedding_generator: "EmbeddingGenerator",
        ticket_repo: "TicketRepository",
        settings: "Settings",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="RAGAgent",
            human_input_mode="NEVER",
            llm_config=False,
            **kwargs,
        )
        self._kb = kb
        self._kb_repo = kb_repo
        self._retriever = retriever
        self._reranker = reranker
        self._rag_generator = rag_generator
        self._embedding_generator = embedding_generator
        self._ticket_repo = ticket_repo
        self._settings = settings

    async def _run_rag(self, msg: dict) -> dict:
        """Execute the full RAG pipeline and return the result dict."""
        ticket_id = uuid.UUID(msg["ticket_id"])
        title: str = msg["title"]
        description: str = msg["description"]
        classification: dict = msg["classification"]

        category = TicketCategory(classification["predicted_category"])

        # RETRIEVING status
        await self._ticket_repo.update_status(ticket_id, TicketStatus.RETRIEVING)

        query_text = f"{title} {description}"
        query_vector = await asyncio.to_thread(self._embedding_generator.encode_single, query_text)

        try:
            candidates = await self._retriever.retrieve(
                query_text=query_text,
                query_vector=query_vector,
                category_filter=category,
            )
        except RAGRetrievalError as exc:
            logger.warning(
                "RAGAgent: retrieval returned no results — proceeding without context",
                extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
            )
            candidates = []

        reranked = await asyncio.to_thread(self._reranker.rerank, candidates) if candidates else []

        # GENERATING status
        await self._ticket_repo.update_status(ticket_id, TicketStatus.GENERATING)

        try:
            resolution_text = await self._rag_generator.generate(
                ticket_title=title,
                ticket_description=description,
                category=category,
                retrieved_entries=reranked,
            )
        except LLMUnavailableError as exc:
            logger.error(
                "RAGAgent: LLM unavailable",
                extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
            )
            return {
                "type": "ERROR",
                "ticket_id": str(ticket_id),
                "error_code": "LLM_UNAVAILABLE",
                "message": str(exc),
            }

        retrieved_entries_summary = [
            {
                "entry_id": str(r.entry.id),
                "title": r.entry.title,
                "similarity_score": round(r.combined_score, 4),
            }
            for r in reranked
        ]

        logger.info(
            "RAGAgent: resolution generated",
            extra={
                "metadata": {
                    "ticket_id": str(ticket_id),
                    "category": category.value,
                    "retrieved_count": len(reranked),
                    "resolution_chars": len(resolution_text),
                }
            },
        )

        return {
            "type": "RESOLUTION_GENERATED",
            "ticket_id": str(ticket_id),
            "resolution_text": resolution_text,
            "retrieved_entries": retrieved_entries_summary,
        }
