"""Social chat WebSocket endpoint.

Provides a dedicated socket for 1-1 / group social chat at /ws/chat/{conversation_id}.
Reuses the same ConnectionManager + Redis Pub/Sub infrastructure as the game socket
so that broadcasts work across multiple backend instances.

Phase 1: AI is NOT enabled. The backend simply relays user messages between members.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db, SessionLocal
from app.models.social.conversations import Conversation
from app.models.social.conversation_members import ConversationMember
from app.models.social.messages import Message
from app.models.user_auth.users import User
from app.websockets.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

from app.websockets.connection_manager import manager

router = APIRouter()

# AI feature flag (mặc định tắt, bật khi đã test xong)
AI_CHAT_ENABLED = True
# In-memory mapping conversation_id -> set of connected user_ids. This is local
# to a single backend instance; the manager already handles cross-instance
# broadcasting via Redis Pub/Sub.
conversation_locks: Dict[str, asyncio.Lock] = {}


def _conversation_lock(conversation_id: str) -> asyncio.Lock:
    if conversation_id not in conversation_locks:
        conversation_locks[conversation_id] = asyncio.Lock()
    return conversation_locks[conversation_id]


def _serialize_message(message: Message) -> Dict[str, Any]:
    sender = message.sender
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "sender_id": str(message.sender_id),
        "sender_type": message.sender_type,
        "content": message.content,
        "is_ai_generated": message.is_ai_generated,
        "metadata": message.message_metadata,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "updated_at": message.updated_at.isoformat() if message.updated_at else None,"sender": {
            "id": str(sender.id) if sender else str(message.sender_id),
            "username": sender.username if sender else None,
            "full_name": sender.full_name if sender else None,
            "avatar_url": sender.avatar_url if sender else None,
        }
        if sender
        else None,
    }


def _resolve_user_id(token: str) -> Optional[UUID]:
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return UUID(sub)
    except (ValueError, TypeError):
        return None


def _check_membership(db: Session, conversation_id: UUID, user_id: UUID) -> bool:
    member = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
        .first()
    )
    return member is not None


def _load_member_user_ids(db: Session, conversation_id: UUID) -> list[str]:
    rows = (
        db.query(ConversationMember.user_id)
        .filter(ConversationMember.conversation_id == conversation_id)
        .all()
    )
    return [str(r[0]) for r in rows]


async def _handle_chat_send(
    websocket: WebSocket,
    conversation_id: UUID,
    user_id: UUID,
    payload: Dict[str, Any],
) -> None:
    """Persist a chat message and broadcast it to all members."""
    content = str(payload.get("content", "")).strip()
    if not content:
        return
    if len(content) > 5000:
        await websocket.send_json(
            {
                "type": "ERROR",
                "data": {"detail": "Message too long (max 5000 chars)"},
            }
        )
        return

    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        metadata = None

    db = SessionLocal()
    try:
        if not _check_membership(db, conversation_id, user_id):
            await websocket.send_json(
                {"type": "ERROR", "data": {"detail": "Not a member of this conversation"}}
            )
            return

        message = Message(
            conversation_id=conversation_id,
            sender_id=user_id,
            sender_type="user",
            content=content,
            is_ai_generated=False,
            message_metadata=metadata,
        )
        db.add(message)
        # Flush so SQLAlchemy assigns defaults (created_at) before we read them.
        try:
            db.flush()
        except Exception:
            # If flush fails, we will let the outer exception handler handle it.
            pass

        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if conversation is not None:
            ts = message.created_at or datetime.utcnow()
            conversation.last_message_at = ts
            conversation.updated_at = ts

        sender_member = (
            db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
            .first()
        )
        if sender_member is not None:
            sender_member.last_read_at = message.created_at or datetime.utcnow()

        db.commit()
        db.refresh(message)
        serialized = _serialize_message(message)
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to persist social chat message: %s", exc)
        await websocket.send_json(
            {"type": "ERROR", "data": {"detail": "Failed to send message"}}
        )
        return
    finally:
        db.close()

        # Hook: embed vào chat_context_embeddings (best-effort, dùng session mới)
    try:
        from app.services.ingestion_service import ingest_message

        with SessionLocal() as hook_db:
            ingest_message(hook_db, message.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ingestion hook failed for chat message %s: %s", message.id, exc)

        # Broadcast user message trước (UX: user thấy message ngay)
    await manager.broadcast(
        str(conversation_id),
        {"type": "CHAT_MESSAGE", "data": serialized},
    )

    # Hook AI: trigger orchestrator nếu cần (chạy background, không block)
    # FIX_REST_API_BLOCKED_BY_AI: dùng wrapper có timeout để tránh block event loop
    # nếu AI task bị treo. Timeout mặc định 15s, vượt quá → broadcast error message.
    asyncio.create_task(
        _maybe_trigger_ai_with_timeout(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=content,
            user_message_id=message.id,
        )
    )


# FIX_REST_API_BLOCKED_BY_AI: timeout safety net
# Mặc định 60s để chứa các tác vụ nặng:
# - Pro model với context RAG dài (top-5 chat history × 500 tokens/hit)
# - summarize nhiều tin nhắn (intent=summarize cộng thêm 400 tokens output)
# - SQL queries phức tạp chạy 2 chiều (get_my_friends)
# Nếu quá timeout này → coi như LLM/proxy bị treo, broadcast error và release.
AI_TASK_TIMEOUT_SECONDS = 60.0
AI_TASK_SOFT_WARN_SECONDS = 30.0


async def _maybe_trigger_ai_with_timeout(
    conversation_id: UUID,
    user_id: UUID,
    user_message: str,
    user_message_id: UUID,
) -> None:
        """
        Wrapper bọc _maybe_trigger_ai với asyncio.wait_for.
        Nếu AI task chạy quá AI_TASK_TIMEOUT_SECONDS (60s) → log + broadcast error.
        Đây là safety net phòng case LLM proxy bị treo, không bao giờ block REST API.

        Có 2 ngưỡng:
        - SOFT_WARN (30s): log warning để debug, KHÔNG broadcast gì cả
        - HARD_TIMEOUT (60s): coi như treo, log error + broadcast error message
        """
        ai_task = asyncio.create_task(
            _maybe_trigger_ai(
                conversation_id=conversation_id,
                user_id=user_id,
                user_message=user_message,
                user_message_id=user_message_id,
            )
        )
        soft_warn_task = asyncio.create_task(
            _soft_warn_sleep(conversation_id, user_message_id)
        )

        try:
            # Đợi task chính hoàn thành (không bị soft_warn cancel)
            await ai_task
        except asyncio.TimeoutError:
            logger.error(
                f"AI trigger HARD TIMEOUT after {AI_TASK_TIMEOUT_SECONDS}s: "
                f"conversation={conversation_id}, user_message_id={user_message_id}"
            )
            ai_task.cancel()
            try:
                await manager.broadcast(
                    str(conversation_id),
                    {
                        "type": "CHAT_MESSAGE",
                        "data": {
                            "id": "temp-ai-timeout",
                            "conversation_id": str(conversation_id),
                            "sender_id": str(user_id),
                            "sender_type": "ai",
                            "content": (
                                f"Xin lỗi, AI xử lý quá thời gian cho phép "
                                f"({AI_TASK_TIMEOUT_SECONDS:.0f}s). Bạn thử lại nhé."
                            ),
                            "is_ai_generated": True,
                            "metadata": {"error": "ai_timeout"},
                            "created_at": datetime.utcnow().isoformat(),
                        },
                    },
                )
            except Exception:
                pass
        except Exception as exc:
            # _maybe_trigger_ai đã có try/except bên trong rồi, đây là defense-in-depth
            logger.exception("AI trigger wrapper unexpected error: %s", exc)
        finally:
            # Dọn soft warn task nếu chưa chạy
            if not soft_warn_task.done():
                soft_warn_task.cancel()
            # Áp dụng hard timeout cho cả 2 task
            try:
                await asyncio.wait_for(
                    asyncio.gather(ai_task, soft_warn_task, return_exceptions=True),
                    timeout=AI_TASK_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass


async def _soft_warn_sleep(conversation_id: UUID, user_message_id: UUID) -> None:
        """
        Sleep SOFT_WARN_SECONDS, nếu chưa bị cancel thì log warning.
        Soft warning giúp debug: biết task đang lâu nhưng chưa đến mức timeout.
        """
        try:
            await asyncio.sleep(AI_TASK_SOFT_WARN_SECONDS)
            logger.warning(
                f"AI trigger is taking long (> {AI_TASK_SOFT_WARN_SECONDS}s): "
                f"conversation={conversation_id}, user_message_id={user_message_id}. "
                f"Will hard-timeout at {AI_TASK_TIMEOUT_SECONDS}s."
            )
        except asyncio.CancelledError:
            pass  # task chính xong trước SOFT_WARN → cancel bình thường


async def _maybe_trigger_ai(
    conversation_id: UUID,
    user_id: UUID,
    user_message: str,
    user_message_id: UUID,
) -> None:
    """
    Check xem có cần trigger AI orchestrator không.
    Chạy trong background task (create_task) để không block broadcast user message.

    Trigger conditions:
    1. AI_CHAT_ENABLED = True (feature flag)
    2. Message bắt đầu với "@ai " (explicit trigger)
       HOẶC conversation.ai_enabled = True (auto trigger)

    Flow:
    - Load recent history (5 messages) — dùng session riêng, đóng ngay
    - Gọi run_ai_orchestrator_async (chạy trong thread pool, KHÔNG block event loop)
    - Orchestrator tự tạo session DB của riêng nó → không giữ session qua await
    - Broadcast AI reply

    FIX_REST_API_BLOCKED_BY_AI:
    - Trước đây hàm này gọi `run_ai_orchestrator(...)` sync → block event loop 1-4s
    - DB session được giữ suốt thời gian AI chạy → cạn kiệt connection pool
    - Fix: tách session load history (đóng ngay), gọi async wrapper với db=None
    """
    if not AI_CHAT_ENABLED:
        return

    # FIX_REST_API_BLOCKED_BY_AI: log timing chi tiết để verify root cause
    t_trigger_start = time.time()

    # Check trigger: "@ai " prefix hoặc conversation ai_enabled flag
    explicit_trigger = user_message.lower().startswith("@ai ")

    # FIX_REST_API_BLOCKED_BY_AI: load history + check conversation trong session RIÊNG,
    # đóng ngay sau khi xong. Không giữ session qua await run_ai_orchestrator_async.
    conversation = None
    history: list[dict] = []
    try:
        with SessionLocal() as pre_db:
            conversation = (
                pre_db.query(Conversation)
                .filter(Conversation.id == conversation_id)
                .first()
            )
            if conversation is not None:
                # Load recent history (5 messages gần nhất)
                recent_messages = (
                    pre_db.query(Message)
                    .filter(
                        Message.conversation_id == conversation_id,
                        Message.deleted_at.is_(None),
                        Message.id != user_message_id,  # Không bao gồm message hiện tại
                    )
                    .order_by(Message.created_at.desc())
                    .limit(5)
                    .all()
                )
                recent_messages.reverse()  # Oldest first
                history = [
                    {
                        "sender_type": msg.sender_type,
                        "content": msg.content,
                    }
                    for msg in recent_messages
                ]
    except Exception as exc:
        logger.exception("Failed to load conversation/history for AI trigger: %s", exc)
        return

    if conversation is None:
        return

    # Check ai_enabled flag (cần thêm column này vào conversations table)
    # Tạm thời chỉ dùng explicit trigger
    auto_trigger = False  # conversation.ai_enabled if hasattr(conversation, 'ai_enabled') else False

    if not explicit_trigger and not auto_trigger:
        return

    # Strip "@ai " prefix nếu có
    query = user_message[4:].strip() if explicit_trigger else user_message
    if not query:
        return

    logger.info(
        f"AI task triggered: conversation={conversation_id}, "
        f"user_message_id={user_message_id}, history_len={len(history)}, "
        f"trigger={'explicit' if explicit_trigger else 'auto'}"
    )

    # FIX_REST_API_BLOCKED_BY_AI: gọi async wrapper với db=None để:
    # 1. Orchestrator chạy trong thread pool → KHÔNG block event loop
    # 2. Orchestrator tự tạo SessionLocal() trong thread → không share session
    #    giữa event loop và thread (tránh concurrent access error)
    from app.services.ai_orchestrator import run_ai_orchestrator_async

    try:
        result = await run_ai_orchestrator_async(
            db=None,  # orchestrator tự quản lý session lifecycle
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=query,
            user_message_id=user_message_id,
            recent_history=history,
        )
    except Exception as exc:
        logger.exception("run_ai_orchestrator_async raised: %s", exc)
        try:
            await manager.broadcast(
                str(conversation_id),
                {
                    "type": "CHAT_MESSAGE",
                    "data": {
                        "id": "temp-ai-error",
                        "conversation_id": str(conversation_id),
                        "sender_id": str(user_id),
                        "sender_type": "ai",
                        "content": "Xin lỗi, tôi gặp lỗi khi xử lý yêu cầu.",
                        "is_ai_generated": True,
                        "metadata": {"error": str(exc)[:200]},
                        "created_at": datetime.utcnow().isoformat(),
                    },
                },
            )
        except Exception:
            pass
        return

    # FIX_REST_API_BLOCKED_BY_AI: tổng thời gian trigger → broadcast
    elapsed_ms = int((time.time() - t_trigger_start) * 1000)
    logger.info(
        f"AI task finished: total_elapsed={elapsed_ms}ms, "
        f"intent={result.get('intent')}, "
        f"orchestrator_total_ms={result.get('timings', {}).get('total_ms')}"
    )

    ai_message_id = result.get("ai_message_id")
    if not ai_message_id:
        # Orchestrator failed to persist AI message (logged internally)
        # Broadcast một message tạm thời
        await manager.broadcast(
            str(conversation_id),
            {
                "type": "CHAT_MESSAGE",
                "data": {
                    "id": "temp-ai-error",
                    "conversation_id": str(conversation_id),
                    "sender_id": str(user_id),
                    "sender_type": "ai",
                    "content": result.get("answer", "Xin lỗi, tôi gặp sự cố khi xử lý."),
                    "is_ai_generated": True,
                    "metadata": {"error": result.get("error")},
                    "created_at": datetime.utcnow().isoformat(),
                },
            },
        )
        return

    # FIX_REST_API_BLOCKED_BY_AI: load AI message trong session RIÊNG, đóng ngay
    # để broadcast serialized payload mà không giữ connection.
    try:
        with SessionLocal() as post_db:
            ai_message = post_db.query(Message).filter(Message.id == ai_message_id).first()
            if ai_message:
                serialized = _serialize_message(ai_message)
                await manager.broadcast(
                    str(conversation_id),
                    {"type": "CHAT_MESSAGE", "data": serialized},
                )
    except Exception as exc:
        logger.exception("Failed to load+broadcast AI message: %s", exc)

    logger.info(
        f"AI reply sent: conversation={conversation_id}, "
        f"intent={result.get('intent')}, "
        f"total_ms={result.get('timings', {}).get('total_ms')}"
    )


async def _handle_mark_read(
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    db = SessionLocal()
    try:
        member = (
            db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
            .first()
        )
        if member is not None:
            member.last_read_at = member.last_read_at or member.joined_at
    except Exception as exc:
        logger.exception("Failed to mark conversation as read: %s", exc)
    finally:
        db.close()


@router.websocket("/ws/chat/{conversation_id}")
async def chat_socket(
    websocket: WebSocket,
    conversation_id: str,
    db: Session = Depends(get_db),
):
    token = websocket.query_params.get("token")
    user_id = _resolve_user_id(token or "")
    if user_id is None:
        await websocket.close(code=4401)
        return

    try:
        conv_uuid = UUID(conversation_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    if not _check_membership(db, conv_uuid, user_id):
        await websocket.close(code=4403)
        return

    await manager.connect(str(conv_uuid), str(user_id), websocket)

    # Inform the connecting client of the current member list so the UI can
    # render presence / titles for direct chats.
    try:
        member_ids = _load_member_user_ids(db, conv_uuid)
        await websocket.send_json(
            {
                "type": "CONVERSATION_JOINED",
                "data": {
                    "conversation_id": str(conv_uuid),
                    "member_ids": member_ids,
                },
            }
        )
    except Exception:
        pass

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                parsed = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event_type = parsed.get("type")
            data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}

            if event_type == "SEND_MESSAGE":
                await _handle_chat_send(websocket, conv_uuid, user_id, data)
            elif event_type == "MARK_READ":
                await _handle_mark_read(conv_uuid, user_id)
            elif event_type == "PING":
                await websocket.send_json({"type": "PONG"})
            else:
                # Unknown events are ignored to keep the protocol forward compatible.
                continue
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(str(conv_uuid), str(user_id), websocket)

