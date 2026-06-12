"""
Qdrant service - quản lý Qdrant client + collection schema.

Theo PHASE2_SETUP.md:
- 4 collections: quiz_embeddings, question_embeddings, retrieval_chunks, chat_context_embeddings
- Vector size lấy từ settings.QDRANT_VECTOR_SIZE (mặc định 768 theo Migration Note)
- Distance lấy từ settings.QDRANT_DISTANCE (mặc định Cosine)
- Tạo payload indexes cho filter nhanh
- ensure_collections() chạy tự động khi backend khởi động
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings

logger = logging.getLogger(__name__)


QUIZ_COLLECTION = "quiz_embeddings"
QUESTION_COLLECTION = "question_embeddings"
CHUNK_COLLECTION = "retrieval_chunks"
CHAT_COLLECTION = "chat_context_embeddings"

ALL_COLLECTIONS = [
    QUIZ_COLLECTION,
    QUESTION_COLLECTION,
    CHUNK_COLLECTION,
    CHAT_COLLECTION,
]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_qdrant() -> QdrantClient:
    """
    Singleton Qdrant client. Lưu ý: client này thread-safe, dùng được cho cả sync.
    Chỉ truyền api_key khi có thật (tránh warning 'insecure connection' khi key rỗng).
    """
    kwargs = {
        "url": settings.QDRANT_URL,
        "timeout": 30.0,
    }
    if settings.QDRANT_API_KEY:
        kwargs["api_key"] = settings.QDRANT_API_KEY
    return QdrantClient(**kwargs)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _distance() -> qm.Distance:
    name = (settings.QDRANT_DISTANCE or "Cosine").lower()
    return {
        "cosine": qm.Distance.COSINE,
        "dot": qm.Distance.DOT,
        "euclid": qm.Distance.EUCLID,
        "euclidean": qm.Distance.EUCLID,
        "manhattan": qm.Distance.MANHATTAN,
    }.get(name, qm.Distance.COSINE)


def _common_indexes() -> List[dict]:
    """
    Khai báo payload index dạng (field_name, field_type) cho 4 collection.
    qdrant-client 1.9.0: dùng create_payload_index(field_name, field_type).
    KHÔNG dùng PayloadIndexInfo (class đó ở 1.9.0 chỉ dùng để mô tả,
    không phải input cho create_payload_index).
    """
    return [
        {"field_name": "source_type", "field_type": qm.PayloadSchemaType.KEYWORD},
        {"field_name": "source_id", "field_type": qm.PayloadSchemaType.KEYWORD},
        {"field_name": "quiz_id", "field_type": qm.PayloadSchemaType.KEYWORD},
        {"field_name": "is_public", "field_type": qm.PayloadSchemaType.BOOL},
        {"field_name": "is_deleted", "field_type": qm.PayloadSchemaType.BOOL},
        {"field_name": "updated_at", "field_type": qm.PayloadSchemaType.DATETIME},
    ]


def _collection_specific_indexes(name: str) -> List[dict]:
    if name == QUESTION_COLLECTION:
        return [
            {"field_name": "question_type", "field_type": qm.PayloadSchemaType.KEYWORD},
        ]
    if name == CHUNK_COLLECTION:
        return [
            {"field_name": "chunk_index", "field_type": qm.PayloadSchemaType.INTEGER},
        ]
    if name == CHAT_COLLECTION:
        return [
            {"field_name": "conversation_id", "field_type": qm.PayloadSchemaType.KEYWORD},
            {"field_name": "sender_id", "field_type": qm.PayloadSchemaType.KEYWORD},
            {"field_name": "is_ai_generated", "field_type": qm.PayloadSchemaType.BOOL},
        ]
    return []


def ensure_collection(name: str) -> None:
    """Tạo collection nếu chưa có, kèm payload indexes."""
    client = get_qdrant()
    exists = client.collection_exists(collection_name=name)
    if not exists:
        logger.info("Creating Qdrant collection %s (dim=%s)", name, settings.QDRANT_VECTOR_SIZE)
        client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(
                size=settings.QDRANT_VECTOR_SIZE,
                distance=_distance(),
            ),
            optimizers_config=qm.OptimizersConfigDiff(default_segment_number=2),
        )

    # payload indexes (idempotent)
    for idx in _common_indexes() + _collection_specific_indexes(name):
        try:
            # qdrant-client 1.9.0 API: create_payload_index(collection_name, field_name, field_type)
            client.create_payload_index(
                collection_name=name,
                field_name=idx["field_name"],
                field_type=idx["field_type"],
            )
        except Exception as e:  # noqa: BLE001
            # index có thể đã tồn tại -> bỏ qua
            logger.debug("Index %s.%s already exists or skipped: %s", name, idx["field_name"], e)


def ensure_collections(
    max_retries: int = 5,
    retry_delay: float = 2.0,
) -> None:
    """
    Tạo 4 collection nếu chưa có. Được gọi khi backend khởi động.

    Retry vì Qdrant có thể chưa sẵn sàng khi backend vừa start
    (depends_on: service_started chỉ chờ container start, không chờ ready).
    """
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            client = get_qdrant()
            client.get_collections()  # trigger kết nối
            for name in ALL_COLLECTIONS:
                ensure_collection(name)
            logger.info("✅ Qdrant collections ready!")
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(
                "Qdrant not ready (attempt %s/%s): %s. Retrying in %.1fs...",
                attempt,
                max_retries,
                e,
                retry_delay,
            )
            if attempt < max_retries:
                time.sleep(retry_delay)
    raise RuntimeError(
        f"Không kết nối được Qdrant tại {settings.QDRANT_URL} "
        f"sau {max_retries} lần thử: {last_err}"
    )


def drop_collection(name: str) -> None:
    client = get_qdrant()
    if client.collection_exists(collection_name=name):
        client.delete_collection(collection_name=name)
        logger.info("Dropped Qdrant collection %s", name)


def drop_all_collections() -> None:
    for name in ALL_COLLECTIONS:
        drop_collection(name)


# ---------------------------------------------------------------------------
# Write / read helpers
# ---------------------------------------------------------------------------


def _string_point_id(s: str) -> str:
    return str(s)


def upsert_points(
    collection: str,
    points: List[qm.PointStruct],
) -> None:
    if not points:
        return
    client = get_qdrant()
    client.upsert(collection_name=collection, points=points, wait=True)


def delete_by_quiz_id(collection: str, quiz_id: str) -> None:
    client = get_qdrant()
    client.delete(
        collection_name=collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="quiz_id",
                        match=qm.MatchValue(value=str(quiz_id)),
                    )
                ]
            )
        ),
    )


def delete_by_source_id(collection: str, source_id: str) -> None:
    client = get_qdrant()
    client.delete(
        collection_name=collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="source_id",
                        match=qm.MatchValue(value=str(source_id)),
                    )
                ]
            )
        ),
    )


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------


def public_filter() -> qm.Filter:
    """
    Filter mặc định cho mọi search request trên quiz/question.
    is_public == true AND is_deleted == false
    """
    return qm.Filter(
        must=[
            qm.FieldCondition(key="is_public", match=qm.MatchValue(value=True)),
            qm.FieldCondition(key="is_deleted", match=qm.MatchValue(value=False)),
        ]
    )


def chat_filter() -> qm.Filter:
    """
    Filter cho collection chat_context_embeddings.
    Chat message là dữ liệu riêng tư theo conversation,
    KHÔNG filter is_public — chỉ loại bỏ soft-deleted.
    """
    return qm.Filter(
        must=[
            qm.FieldCondition(key="is_deleted", match=qm.MatchValue(value=False)),
        ]
    )


def search(
    collection: str,
    query_vector: List[float],
    top_k: int = 10,
    extra_filter: Optional[qm.Filter] = None,
    filter_type: str = "public",
) -> List[Dict[str, Any]]:
    """
    Search top-k bằng cosine (hoặc distance đã cấu hình).

    filter_type:
        - "public" (mặc định): is_public=true AND is_deleted=false (quiz/question)
        - "chat": chỉ is_deleted=false (chat_context_embeddings)
        - "none": không filter gì thêm
    Có thể thêm extra_filter để narrow thêm (AND với filter mặc định).
    """
    if filter_type == "chat":
        base = chat_filter()
    elif filter_type == "none":
        base = None
    else:
        base = public_filter()

    if base is None:
        merged = extra_filter
    elif extra_filter is None:
        merged = base
    else:
        merged = qm.Filter(must=(base.must or []) + (extra_filter.must or []))

    client = get_qdrant()
    # qdrant-client >= 1.10 dùng query_points thay cho search (deprecated)
    try:
        resp = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            query_filter=merged,
            with_payload=True,
            with_vectors=False,
        )
        hits = resp.points
    except AttributeError:
        # Fallback cho bản cũ
        hits = client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=merged,
            with_payload=True,
            with_vectors=False,
        )
    results: List[Dict[str, Any]] = []
    for h in hits:
        results.append(
            {
                "id": _string_point_id(h.id) if not isinstance(h.id, str) else h.id,
                "score": float(h.score) if h.score is not None else 0.0,
                "payload": dict(h.payload or {}),
            }
        )
    return results
