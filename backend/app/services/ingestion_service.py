"""
Ingestion service - PostgreSQL → Qdrant mapping.

Theo PHASE2_SETUP.md:
- ingest_quiz(db, quiz_id): upsert 1 quiz point + N question points
- remove_quiz_from_index(quiz_id): xóa hết point theo quiz_id
- ingest_quiz_if_public: chỉ ingest khi quiz public và chưa bị xóa
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional
from uuid import UUID

from qdrant_client.http import models as qm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.quiz.questions import Question
from app.models.quiz.quizzes import Quiz
from app.models.social.messages import Message
from app.services import embedding_service
from app.services import qdrant_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_quiz_payload(quiz: Quiz) -> dict:
    question_count = len(quiz.questions) if quiz.questions is not None else 0
    return {
        "source_type": "quiz",
        "source_id": str(quiz.id),
        "quiz_id": str(quiz.id),
        "is_public": bool(quiz.is_public),
        "is_deleted": bool(getattr(quiz, "is_deleted", False)),
        "title": quiz.title or "",
        "description": quiz.description or "",
        "question_count": int(question_count),
        "created_at": _iso(getattr(quiz, "created_at", None)),
        "updated_at": _iso(getattr(quiz, "updated_at", None)),
    }


def _build_question_payload(question: Question, quiz: Quiz) -> dict:
    return {
        "source_type": "question",
        "source_id": str(question.id),
        "quiz_id": str(quiz.id),
        "is_public": bool(quiz.is_public),
        "is_deleted": bool(getattr(quiz, "is_deleted", False)),
        "content": question.content or "",
        "question_type": question.question_type or "",
        "quiz_title": quiz.title or "",
        "created_at": _iso(getattr(question, "created_at", None)),
        "updated_at": _iso(getattr(question, "updated_at", None)),
    }


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:  # noqa: BLE001
        return None


def _vector_dim() -> int:
    return settings.QDRANT_VECTOR_SIZE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _get_quiz(db: Session, quiz_id: UUID) -> Optional[Quiz]:
    return (
        db.query(Quiz)
        .filter(Quiz.id == quiz_id, Quiz.is_deleted.is_(False))
        .first()
    )


def _should_index(quiz: Quiz) -> bool:
    return bool(quiz.is_public) and not bool(getattr(quiz, "is_deleted", False))


def ingest_quiz(db: Session, quiz_id: UUID) -> None:
    """
    Index 1 quiz (point vào quiz_embeddings) + N question (vào question_embeddings).
    Chỉ thực sự upsert khi quiz public và chưa bị xóa; nếu không thì xóa point cũ.
    """
    quiz = _get_quiz(db, quiz_id)
    if quiz is None:
        # quiz bị xóa cứng: dọn index luôn
        remove_quiz_from_index(str(quiz_id))
        return

    if not _should_index(quiz):
        # private / soft-deleted: dọn khỏi index
        remove_quiz_from_index(str(quiz_id))
        return

    # Load questions nếu chưa có
    questions: List[Question] = list(quiz.questions or [])
    if not questions:
        questions = (
            db.query(Question).filter(Question.quiz_id == quiz.id).all()
        )

    # --- Quiz point ---
    quiz_text = embedding_service.build_quiz_text(quiz)
    try:
        quiz_vector = embedding_service.embed_passages([quiz_text])[0]
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to embed quiz %s: %s", quiz_id, e)
        return

    quiz_point = qm.PointStruct(
        id=str(quiz.id),
        vector=quiz_vector,
        payload=_build_quiz_payload(quiz),
    )

    # --- Question points ---
    question_points: List[qm.PointStruct] = []
    if questions:
        question_texts = [
            embedding_service.build_question_text(q, quiz) for q in questions
        ]
        try:
            question_vectors = embedding_service.embed_passages(question_texts)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to embed questions for quiz %s: %s", quiz_id, e)
            return

        for q_obj, vec in zip(questions, question_vectors):
            question_points.append(
                qm.PointStruct(
                    id=str(q_obj.id),
                    vector=vec,
                    payload=_build_question_payload(q_obj, quiz),
                )
            )

    qdrant_service.upsert_points(qdrant_service.QUIZ_COLLECTION, [quiz_point])
    if question_points:
        qdrant_service.upsert_points(
            qdrant_service.QUESTION_COLLECTION, question_points
        )

    logger.info(
        "Ingested quiz %s (1 + %s questions, dim=%s)",
        quiz_id,
        len(question_points),
        _vector_dim(),
    )


def remove_quiz_from_index(quiz_id: str) -> None:
    """Xóa toàn bộ point thuộc 1 quiz khỏi mọi collection liên quan."""
    qdrant_service.delete_by_quiz_id(qdrant_service.QUIZ_COLLECTION, quiz_id)
    qdrant_service.delete_by_quiz_id(qdrant_service.QUESTION_COLLECTION, quiz_id)
    logger.info("Removed quiz %s from index", quiz_id)


def reingest_all_public_quizzes(db: Session, batch_size: int = 50) -> int:
    """
    Backfill: index lại toàn bộ quiz public (chưa xóa) trong DB.
    Trả về số quiz đã ingest.
    """
    count = 0
    quizzes: Iterable[Quiz] = (
        db.query(Quiz)
        .filter(Quiz.is_deleted.is_(False), Quiz.is_public.is_(True))
        .yield_per(batch_size)
    )
    for quiz in quizzes:
        try:
            ingest_quiz(db, quiz.id)
            count += 1
        except Exception as e:  # noqa: BLE001
            logger.exception("Backfill failed for quiz %s: %s", quiz.id, e)
            db.rollback()
            continue
        if count % batch_size == 0:
            logger.info("Backfill progress: %s quizzes", count)
    return count


# ---------------------------------------------------------------------------
# Chat message ingestion (RAG cho social chat)
# ---------------------------------------------------------------------------
# Tin nhắn chat là dữ liệu riêng tư từng conversation, không filter is_public.
# Chỉ filter is_deleted (theo Message.deleted_at).
# Mục đích: retrieval context cho intent router / AI reply (Phase 3+).
# ---------------------------------------------------------------------------


def _build_message_payload(message: Message) -> dict:
    is_deleted = message.deleted_at is not None
    return {
        "source_type": "chat_message",
        "source_id": str(message.id),
        "quiz_id": "",  # giữ schema đồng nhất với quiz/question
        "conversation_id": str(message.conversation_id),
        "sender_id": str(message.sender_id),
        "sender_type": message.sender_type or "user",
        "is_ai_generated": bool(message.is_ai_generated),
        "is_deleted": is_deleted,
        "content": message.content or "",
        "created_at": _iso(getattr(message, "created_at", None)),
        "updated_at": _iso(getattr(message, "updated_at", None)),
    }


def _get_message(db: Session, message_id: UUID) -> Optional[Message]:
    return db.query(Message).filter(Message.id == message_id).first()


def ingest_message(db: Session, message_id: UUID) -> None:
    """
    Index 1 message vào chat_context_embeddings.
    
    RULES:
    - KHÔNG embed AI messages (is_ai_generated=True)
    - KHÔNG embed messages quá ngắn (< 5 từ)
    - Nếu message bị soft-delete (deleted_at set) → dọn khỏi index.
    - Nếu message còn sống → embed content + upsert point.
    """
    message = _get_message(db, message_id)
    if message is None:
        # bị xóa cứng (cascade hoặc admin): dọn index
        qdrant_service.delete_by_source_id(
            qdrant_service.CHAT_COLLECTION, str(message_id)
        )
        return

    if message.deleted_at is not None:
        # soft-delete: dọn khỏi index
        qdrant_service.delete_by_source_id(
            qdrant_service.CHAT_COLLECTION, str(message_id)
        )
        return
    
    # RULE 1: KHÔNG embed AI messages
    if message.is_ai_generated:
        logger.debug(
            f"Skip embedding message {message_id}: is_ai_generated=True"
        )
        # Xóa khỏi index nếu trước đó đã embed nhầm
        qdrant_service.delete_by_source_id(
            qdrant_service.CHAT_COLLECTION, str(message_id)
        )
        return

    content = (message.content or "").strip()
    if not content:
        # message rỗng: không ingest (không có gì để search)
        qdrant_service.delete_by_source_id(
            qdrant_service.CHAT_COLLECTION, str(message_id)
        )
        return
    
    # RULE 2: KHÔNG embed messages quá ngắn (< 5 từ)
    word_count = len(content.split())
    if word_count < 5:
        logger.debug(
            f"Skip embedding message {message_id}: too short ({word_count} words)"
        )
        # Xóa khỏi index nếu trước đó đã embed nhầm
        qdrant_service.delete_by_source_id(
            qdrant_service.CHAT_COLLECTION, str(message_id)
        )
        return

    try:
        vector = embedding_service.embed_passages([content])[0]
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to embed message %s: %s", message_id, e)
        return

    point = qm.PointStruct(
        id=str(message.id),
        vector=vector,
        payload=_build_message_payload(message),
    )
    qdrant_service.upsert_points(qdrant_service.CHAT_COLLECTION, [point])
    logger.info(
        "Ingested message %s (conv=%s, words=%s, dim=%s)",
        message_id,
        message.conversation_id,
        word_count,
        _vector_dim(),
    )


def remove_message_from_index(message_id: str) -> None:
    """Xóa 1 message point khỏi chat_context_embeddings."""
    qdrant_service.delete_by_source_id(
        qdrant_service.CHAT_COLLECTION, message_id
    )
    logger.info("Removed message %s from index", message_id)


def reingest_all_messages(
    db: Session,
    batch_size: int = 100,
    include_deleted: bool = False,
) -> int:
    """
    Backfill: index lại toàn bộ message trong DB.
    Mặc định BỎ QUA message đã soft-delete (deleted_at IS NOT NULL).
    Trả về số message đã ingest thành công.
    """
    count = 0
    q = db.query(Message)
    if not include_deleted:
        q = q.filter(Message.deleted_at.is_(None))
    messages: Iterable[Message] = q.yield_per(batch_size)
    for message in messages:
        try:
            ingest_message(db, message.id)
            count += 1
        except Exception as e:  # noqa: BLE001
            logger.exception("Backfill failed for message %s: %s", message.id, e)
            db.rollback()
            continue
        if count % batch_size == 0:
            logger.info("Backfill message progress: %s", count)
    return count
