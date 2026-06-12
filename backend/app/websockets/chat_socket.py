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
    asyncio.create_task(
        _maybe_trigger_ai(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=content,
            user_message_id=message.id,
        )
    )


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
    - Load recent history (5 messages)
    - Run orchestrator (router → tool → composer → persist)
    - Broadcast AI reply
    """
    if not AI_CHAT_ENABLED:
        return

    # Check trigger: "@ai " prefix hoặc conversation ai_enabled flag
    explicit_trigger = user_message.lower().startswith("@ai ")
    
    db = SessionLocal()
    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
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
        
        # Load recent history (5 messages gần nhất)
        recent_messages = (
            db.query(Message)
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
        
        # Run AI orchestrator
        from app.services.ai_orchestrator import run_ai_orchestrator
        
        result = run_ai_orchestrator(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=query,
            user_message_id=user_message_id,
            recent_history=history,
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
        
        # Load AI message từ DB để broadcast đúng format
        ai_message = db.query(Message).filter(Message.id == ai_message_id).first()
        if ai_message:
            serialized = _serialize_message(ai_message)
            await manager.broadcast(
                str(conversation_id),
                {"type": "CHAT_MESSAGE", "data": serialized},
            )
        
        logger.info(
            f"AI reply sent: conversation={conversation_id}, "
            f"intent={result.get('intent')}, "
            f"total_ms={result.get('timings', {}).get('total_ms')}"
        )
    
    except Exception as exc:
        logger.exception("AI trigger failed: %s", exc)
        # Best-effort: broadcast error message
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
    finally:
        db.close()


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

