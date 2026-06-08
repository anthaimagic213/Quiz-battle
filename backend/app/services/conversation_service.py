from uuid import UUID
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, func
from fastapi import HTTPException, status

from app.models.social.conversations import Conversation
from app.models.social.conversation_members import ConversationMember
from app.models.social.messages import Message
from app.models.user_auth.users import User
from app.schemas.social import ConversationCreate, ConversationUpdate, OtherMemberInfo

class ConversationService:
    @staticmethod
    def create_conversation(db: Session, creator_id: UUID, data: ConversationCreate) -> Conversation:
        if data.type == "direct":
            if not data.member_ids or len(data.member_ids) != 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Direct conversation requires exactly one other user"
                )
            return ConversationService.create_direct_conversation(db, creator_id, data.member_ids[0])
        else:
            return ConversationService.create_group_conversation(db, creator_id, data)

    @staticmethod
    def create_direct_conversation(db: Session, user_id_1: UUID, user_id_2: UUID) -> Conversation:
        """Create or get a direct conversation between two users"""
        if user_id_1 == user_id_2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create conversation with yourself"
            )

        # Create direct_key (sorted user IDs)
        direct_key = "|".join(sorted([str(user_id_1), str(user_id_2)]))

        existing = db.query(Conversation).filter(Conversation.direct_key == direct_key).first()
        if existing:
            return existing

        conversation = Conversation(
            type="direct",
            direct_key=direct_key
        )
        db.add(conversation)
        db.flush()

        member_1 = ConversationMember(conversation_id=conversation.id, user_id=user_id_1)
        member_2 = ConversationMember(conversation_id=conversation.id, user_id=user_id_2)
        db.add(member_1)
        db.add(member_2)
        db.commit()
        db.refresh(conversation)
        return conversation

    @staticmethod
    def create_group_conversation(db: Session, creator_id: UUID, data: ConversationCreate) -> Conversation:
        """Create a group conversation"""
        if data.type != "group":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use create_direct_conversation for direct conversations"
            )

        if not data.title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group conversation requires a title"
            )

        conversation = Conversation(
            type="group",
            title=data.title
        )
        db.add(conversation)
        db.flush()

        creator_member = ConversationMember(
            conversation_id=conversation.id,
            user_id=creator_id,
            role="admin"
        )
        db.add(creator_member)

        if data.member_ids:
            for member_id in data.member_ids:
                if member_id != creator_id:
                    member = ConversationMember(
                        conversation_id=conversation.id,
                        user_id=member_id
                    )
                    db.add(member)

        db.commit()
        db.refresh(conversation)
        return conversation

    @staticmethod
    def get_conversation_details(db: Session, conversation_id: UUID, user_id: UUID) -> Dict[str, Any]:
        conversation = ConversationService.get_conversation(db, conversation_id, user_id)
        message_count = len(conversation.messages) if hasattr(conversation, "messages") else 0
        return {
            **conversation.__dict__,
            "message_count": message_count,
            "members": conversation.members,
        }

    @staticmethod
    def get_conversation(db: Session, conversation_id: UUID, user_id: UUID) -> Conversation:
        """Get a conversation if user is member"""
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

        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        return conversation

    @staticmethod
    def get_user_conversations(db: Session, user_id: UUID) -> List[Conversation]:
        """Get all conversations for a user"""
        return db.query(Conversation).join(
            ConversationMember,
            Conversation.id == ConversationMember.conversation_id
        ).filter(ConversationMember.user_id == user_id).order_by(
            desc(Conversation.last_message_at)
        ).all()

    @staticmethod
    def update_conversation(db: Session, conversation_id: UUID, user_id: UUID, data: ConversationUpdate) -> Conversation:
        """Update conversation (admin only for groups)"""
        conversation = ConversationService.get_conversation(db, conversation_id, user_id)

        if conversation.type == "group":
            member = db.query(ConversationMember).filter(
                and_(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.user_id == user_id
                )
            ).first()

            if member.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only admin can update group conversation"
                )

        if data.title:
            conversation.title = data.title

        conversation.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(conversation)
        return conversation

    # ====================================================================
    # Enriched helpers for the social chat UI
    # ====================================================================

    @staticmethod
    def _serialize_user(user: Optional[User]) -> Optional[Dict[str, Any]]:
        if user is None:
            return None
        return {
            "id": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
        }

    @staticmethod
    def _build_conversation_payload(
        db: Session,
        conversation: Conversation,
        viewer_id: UUID,
    ) -> Dict[str, Any]:
        other_member = ConversationService._get_other_member(db, conversation, viewer_id)
        last_preview = ConversationService._get_last_message_preview(db, conversation.id)
        unread = ConversationService._get_unread_count(db, conversation.id, viewer_id)

        base = {
            "id": str(conversation.id),
            "type": conversation.type,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "last_message_at": conversation.last_message_at,
            "other_member": ConversationService._serialize_user(other_member),
            "last_message_preview": last_preview,
            "unread_count": unread,
        }
        return base

    @staticmethod
    def _get_other_member(
        db: Session, conversation: Conversation, viewer_id: UUID
    ) -> Optional[User]:
        if conversation.type != "direct":
            return None
        member_row = (
            db.query(ConversationMember)
            .options(joinedload(ConversationMember.user))
            .filter(ConversationMember.conversation_id == conversation.id)
            .all()
        )
        for m in member_row:
            if m.user_id != viewer_id:
                return m.user
        return None

    @staticmethod
    def _get_last_message_preview(db: Session, conversation_id: UUID) -> Optional[str]:
        msg = (
            db.query(Message)
            .filter(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.deleted_at.is_(None),
                )
            )
            .order_by(desc(Message.created_at))
            .first()
        )
        if msg is None:
            return None
        preview = msg.content or ""
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return preview

    @staticmethod
    def _get_unread_count(db: Session, conversation_id: UUID, user_id: UUID) -> int:
        member = (
            db.query(ConversationMember)
            .filter(
                and_(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.user_id == user_id,
                )
            )
            .first()
        )
        if member is None:
            return 0
        # We treat any message from a sender that isn't the viewer, created
        # after the viewer's last_read_at, as unread. If last_read_at is None
        # we count everything (e.g. brand-new conversation).
        query = db.query(func.count(Message.id)).filter(
            and_(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
                Message.sender_id != user_id,
            )
        )
        if member.last_read_at is not None:
            query = query.filter(Message.created_at > member.last_read_at)
        return int(query.scalar() or 0)

    @staticmethod
    def create_or_get_direct_with_member(
        db: Session, viewer_id: UUID, other_user_id: UUID
    ) -> Dict[str, Any]:
        """Create the direct conversation (if missing) and return the enriched payload."""
        conversation = ConversationService.create_direct_conversation(db, viewer_id, other_user_id)
        return ConversationService._build_conversation_payload(db, conversation, viewer_id)

    @staticmethod
    def list_user_conversations_with_member(
        db: Session, user_id: UUID
    ) -> List[Dict[str, Any]]:
        conversations = (
            db.query(Conversation)
            .join(ConversationMember, Conversation.id == ConversationMember.conversation_id)
            .filter(ConversationMember.user_id == user_id)
            .order_by(desc(Conversation.last_message_at), desc(Conversation.updated_at))
            .all()
        )
        return [
            ConversationService._build_conversation_payload(db, conv, user_id)
            for conv in conversations
        ]
