from uuid import UUID
from datetime import datetime
from typing import List, Tuple, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc
from fastapi import HTTPException, status

from app.models.social.messages import Message
from app.models.social.conversations import Conversation
from app.models.social.conversation_members import ConversationMember
from app.schemas.social import MessageCreate, MessageUpdate, MessageListResponse, MessageDetailResponse
from app.services.conversation_service import ConversationService


def _maybe_ingest_message(db: Session, message_id) -> None:
    """
    Best-effort: embed message vào chat_context_embeddings.
    Lỗi embed/Qdrant chỉ log warning, không phá luồng CRUD chat.
    """
    try:
        from app.services.ingestion_service import ingest_message

        ingest_message(db, message_id)
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Ingestion hook failed for message %s: %s", message_id, e
        )


def _maybe_remove_message_from_index(message_id) -> None:
    try:
        from app.services.ingestion_service import remove_message_from_index

        remove_message_from_index(str(message_id))
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Remove-from-index failed for message %s: %s", message_id, e
        )

class MessageService:
    @staticmethod
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
            "created_at": message.created_at,
            "updated_at": message.updated_at,
            "sender_username": sender.username if sender else None,
            "sender_full_name": sender.full_name if sender else None,
            "sender_avatar_url": sender.avatar_url if sender else None,
        }

    @staticmethod
    def create_message(db: Session, conversation_id: UUID, sender_id: UUID, data: MessageCreate) -> Dict[str, Any]:
        """Create a message in a conversation"""
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        member = db.query(ConversationMember).filter(
            and_(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == sender_id
            )
        ).first()

        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this conversation"
            )

        message = Message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            content=data.content,
            message_metadata=data.metadata,
        )
        db.add(message)

        conversation.last_message_at = datetime.utcnow()
        member.last_read_at = datetime.utcnow()

        db.commit()
        db.refresh(message)

        # Hook: embed vào chat_context_embeddings (best-effort)
        _maybe_ingest_message(db, message.id)

        return MessageService._serialize_message(message)

    @staticmethod
    def get_messages_response(db: Session, conversation_id: UUID, user_id: UUID, limit: int = 50, offset: int = 0) -> MessageListResponse:
        """Get messages from a conversation with detailed response"""
        conversation = ConversationService.get_conversation(db, conversation_id, user_id)

        total = db.query(Message).filter(
            and_(
                Message.conversation_id == conversation_id,
                Message.deleted_at == None
            )
        ).count()

        messages = (
            db.query(Message)
            .options(joinedload(Message.sender))
            .filter(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.deleted_at == None
                )
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
            .all()
        )

        messages.reverse()

        message_details = [MessageService._serialize_message(msg) for msg in messages]
        message_models = [MessageDetailResponse(**m) for m in message_details]

        return MessageListResponse(
            messages=message_models,
            total=total,
            page=offset // limit + 1,
            page_size=limit,
        )

    @staticmethod
    def update_message(db: Session, message_id: UUID, user_id: UUID, data: MessageUpdate) -> Dict[str, Any]:
        """Update a message (owner only)"""
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        if message.sender_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own messages"
            )

        message.content = data.content
        message.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(message)

        # Hook: re-ingest sau update (best-effort)
        _maybe_ingest_message(db, message.id)

        return MessageService._serialize_message(message)

    @staticmethod
    def delete_message(db: Session, message_id: UUID, user_id: UUID) -> Message:
        """Soft delete a message (owner only)"""
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        if message.sender_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own messages"
            )

        message.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(message)

        # Hook: dọn khỏi index khi soft-delete (best-effort)
        _maybe_remove_message_from_index(message.id)

        return message

    @staticmethod
    def mark_as_read(db: Session, conversation_id: UUID, user_id: UUID) -> ConversationMember:
        """Mark conversation as read"""
        member = db.query(ConversationMember).filter(
            and_(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id
            )
        ).first()

        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this conversation"
            )

        member.last_read_at = datetime.utcnow()
        db.commit()
        db.refresh(member)
        return member
