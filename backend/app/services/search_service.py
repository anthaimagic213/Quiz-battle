"""
Search service - semantic search với filter public/deleted.

Theo PHASE2_SETUP.md:
- search_quizzes(query, top_k) -> list[hit]
- search_questions(query, top_k) -> list[hit]
- Mỗi hit có id, score, payload
- Default filter: is_public=true AND is_deleted=false
- Có thể chỉnh candidate multiplier cho rerank (mặc định 3)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from qdrant_client.http import models as qm

from app.core.config import settings
from app.services import embedding_service
from app.services import qdrant_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(query: str, top_k: int) -> None:
    if not query or not query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query string 'q' is required and cannot be empty.",
        )
    if top_k < 1 or top_k > settings.RETRIEVAL_MAX_TOP_K:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"top_k must be in [1, {settings.RETRIEVAL_MAX_TOP_K}]",
        )


def _clamp_top_k(top_k: Optional[int]) -> int:
    if top_k is None or top_k <= 0:
        return settings.RETRIEVAL_DEFAULT_TOP_K
    return min(int(top_k), settings.RETRIEVAL_MAX_TOP_K)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _format_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Đảm bảo output có id, score, payload chuẩn, score nằm trong [0,1]."""
    out: List[Dict[str, Any]] = []
    for h in hits:
        score = h.get("score")
        if score is not None:
            # Cosine similarity của qdrant trả về trong khoảng [-1, 1] (với raw cosine)
            # hoặc [0, 1] (với normalized vectors). Chuẩn hóa nhẹ về [0, 1].
            try:
                s = float(score)
                if s < 0:
                    s = 0.0
                elif s > 1:
                    s = 1.0
            except (TypeError, ValueError):
                s = 0.0
        else:
            s = 0.0
        out.append(
            {
                "id": str(h.get("id")),
                "score": s,
                "payload": h.get("payload") or {},
            }
        )
    return out


def _search_collection(
    collection: str,
    query: str,
    top_k: int,
    extra_filter: Optional[qm.Filter] = None,
) -> List[Dict[str, Any]]:
    vector = embedding_service.embed_query(query)
    candidate_k = min(
        top_k * settings.RETRIEVAL_CANDIDATE_MULTIPLIER,
        settings.RETRIEVAL_MAX_TOP_K,
    )
    hits = qdrant_service.search(
        collection=collection,
        query_vector=vector,
        top_k=candidate_k,
        extra_filter=extra_filter,
    )
    return _format_hits(hits[:top_k])


def search_quizzes(query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
    """Semantic search trên quiz_embeddings."""
    top_k = _clamp_top_k(top_k)
    _validate(query, top_k)
    try:
        return _search_collection(qdrant_service.QUIZ_COLLECTION, query, top_k)
    except RuntimeError as e:
        logger.exception("search_quizzes failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search service unavailable: {e}",
        ) from e


def search_questions(query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
    """Semantic search trên question_embeddings."""
    top_k = _clamp_top_k(top_k)
    _validate(query, top_k)
    try:
        return _search_collection(qdrant_service.QUESTION_COLLECTION, query, top_k)
    except RuntimeError as e:
        logger.exception("search_questions failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search service unavailable: {e}",
        ) from e


def search_messages(
    query: str,
    conversation_id: str,
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Semantic search trên chat_context_embeddings, narrowed theo conversation_id.

    Bảo mật: chỉ search trong 1 conversation cụ thể (caller phải check membership trước).
    Filter: is_deleted=false AND conversation_id=<id>.
    """
    top_k = _clamp_top_k(top_k)
    _validate(query, top_k)
    if not conversation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="conversation_id is required for message search.",
        )
    extra = qm.Filter(
        must=[
            qm.FieldCondition(
                key="conversation_id",
                match=qm.MatchValue(value=str(conversation_id)),
            ),
        ]
    )
    vector = embedding_service.embed_query(query)
    candidate_k = min(
        top_k * settings.RETRIEVAL_CANDIDATE_MULTIPLIER,
        settings.RETRIEVAL_MAX_TOP_K,
    )
    try:
        hits = qdrant_service.search(
            collection=qdrant_service.CHAT_COLLECTION,
            query_vector=vector,
            top_k=candidate_k,
            extra_filter=extra,
            filter_type="chat",
        )
    except RuntimeError as e:
        logger.exception("search_messages failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search service unavailable: {e}",
        ) from e
    return _format_hits(hits[:top_k])
