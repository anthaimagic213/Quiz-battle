from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List
from enum import Enum


class ConversationType(str, Enum):
    DIRECT = "direct"
    GROUP = "group"


class SenderType(str, Enum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"


# ============= Friend Request Schemas =============

class FriendRequestCreate(BaseModel):
    addressee_id: UUID


class FriendRequestStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(accepted|rejected)$")


class FriendRequestResponse(BaseModel):
    id: UUID
    requester_id: UUID
    addressee_id: UUID
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============= Friendship Schemas =============

class FriendshipResponse(BaseModel):
    id: UUID
    user_id_1: UUID
    user_id_2: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============= Conversation Schemas =============

class ConversationCreate(BaseModel):
    type: ConversationType
    title: Optional[str] = None
    member_ids: Optional[List[UUID]] = None  # for group conversations


class ConversationUpdate(BaseModel):
    title: Optional[str] = None


class ConversationResponse(BaseModel):
    id: UUID
    type: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime]

    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationResponse):
    members: List["ConversationMemberResponse"] = []
    message_count: Optional[int] = None


class OtherMemberInfo(BaseModel):
    id: UUID
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class ConversationWithMemberResponse(ConversationResponse):
    """Conversation payload that also exposes the other member's profile.

    For direct chats the UI needs to know the friend's name/avatar to render
    the chat header, so we attach that here as a convenience.
    """

    other_member: Optional[OtherMemberInfo] = None
    last_message_preview: Optional[str] = None
    unread_count: Optional[int] = None


# ============= Conversation Member Schemas =============

class ConversationMemberResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    user_id: UUID
    role: str
    last_read_at: Optional[datetime]
    joined_at: datetime

    class Config:
        from_attributes = True


# ============= Message Schemas =============

class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    metadata: Optional[dict] = None


class MessageUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    sender_type: str
    content: str
    is_ai_generated: bool
    metadata: Optional[dict]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageDetailResponse(MessageResponse):
    sender_username: Optional[str] = None
    sender_avatar_url: Optional[str] = None


class MessageListResponse(BaseModel):
    messages: List[MessageDetailResponse]
    total: int
    page: int
    page_size: int


# Update forward refs
ConversationDetailResponse.model_rebuild()
