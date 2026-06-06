from uuid import UUID
from datetime import datetime
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from typing import List

from app.models.user_auth.users import User
from app.models.social.friendships import Friendship
from app.models.social.friend_requests import FriendRequest
from app.models.social.conversations import Conversation
from app.models.social.conversation_members import ConversationMember
from app.models.social.messages import Message
from app.schemas.social import (
    FriendRequestCreate,
    FriendRequestStatusUpdate,
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageUpdate,
)
from fastapi import HTTPException, status



class FriendshipService:
    @staticmethod
    def send_friend_request(db: Session, requester_id: UUID, data: FriendRequestCreate) -> FriendRequest:
        """Send a friend request"""
        if requester_id == data.addressee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send friend request to yourself"
            )

        addressee = db.query(User).filter(User.id == data.addressee_id).first()
        if not addressee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        existing_request = db.query(FriendRequest).filter(
            and_(
                FriendRequest.requester_id == requester_id,
                FriendRequest.addressee_id == data.addressee_id,
                FriendRequest.status == "pending"
            )
        ).first()

        if existing_request:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Friend request already sent"
            )

        existing_friendship = db.query(Friendship).filter(
            or_(
                and_(Friendship.user_id_1 == requester_id, Friendship.user_id_2 == data.addressee_id),
                and_(Friendship.user_id_1 == data.addressee_id, Friendship.user_id_2 == requester_id)
            )
        ).first()

        if existing_friendship:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Already friends"
            )

        friend_request = FriendRequest(
            requester_id=requester_id,
            addressee_id=data.addressee_id,
            status="pending"
        )
        db.add(friend_request)
        db.commit()
        db.refresh(friend_request)
        return friend_request

    @staticmethod
    def respond_friend_request(db: Session, request_id: UUID, user_id: UUID, data: FriendRequestStatusUpdate) -> FriendRequest:
        """Accept or reject a friend request"""
        friend_request = db.query(FriendRequest).filter(FriendRequest.id == request_id).first()
        if not friend_request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Friend request not found"
            )

        if friend_request.addressee_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only respond to your own friend requests"
            )

        if friend_request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Friend request is no longer pending"
            )

        if data.status == "accepted":
            friendship = Friendship(
                user_id_1=friend_request.requester_id,
                user_id_2=friend_request.addressee_id
            )
            db.add(friendship)

        friend_request.status = data.status
        friend_request.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(friend_request)
        return friend_request

    @staticmethod
    def get_pending_requests(db: Session, user_id: UUID) -> List[FriendRequest]:
        """Get pending friend requests for a user"""
        return db.query(FriendRequest).filter(
            and_(
                FriendRequest.addressee_id == user_id,
                FriendRequest.status == "pending"
            )
        ).order_by(desc(FriendRequest.created_at)).all()

    @staticmethod
    def get_friends(db: Session, user_id: UUID) -> List[Friendship]:
        """Get all friendships for a user"""
        return db.query(Friendship).filter(
            or_(
                Friendship.user_id_1 == user_id,
                Friendship.user_id_2 == user_id
            )
        ).all()


class ConversationService:
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


class MessageService:
    @staticmethod
    def create_message(db: Session, conversation_id: UUID, sender_id: UUID, data: MessageCreate) -> Message:
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
            metadata=data.metadata
        )
        db.add(message)

        conversation.last_message_at = datetime.utcnow()
        member.last_read_at = datetime.utcnow()

        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def get_messages(db: Session, conversation_id: UUID, user_id: UUID, limit: int = 50, offset: int = 0) -> Tuple[List[Message], int]:
        """Get messages from a conversation"""
        conversation = ConversationService.get_conversation(db, conversation_id, user_id)

        total = db.query(Message).filter(
            and_(
                Message.conversation_id == conversation_id,
                Message.deleted_at == None
            )
        ).count()

        messages = db.query(Message).filter(
            and_(
                Message.conversation_id == conversation_id,
                Message.deleted_at == None
            )
        ).order_by(desc(Message.created_at)).limit(limit).offset(offset).all()

        messages.reverse()
        return messages, total

    @staticmethod
    def update_message(db: Session, message_id: UUID, user_id: UUID, data: MessageUpdate) -> Message:
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
        return message

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
