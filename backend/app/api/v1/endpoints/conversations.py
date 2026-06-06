from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user
from app.models.user_auth.users import User
from app.schemas.social import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationDetailResponse,
)
from app.services.social_service import ConversationService

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
)


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new conversation (direct or group)"""
    if data.type == "direct":
        if not data.member_ids or len(data.member_ids) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Direct conversation requires exactly one other user"
            )
        conversation = ConversationService.create_direct_conversation(
            db, current_user.id, data.member_ids[0]
        )
    else:
        conversation = ConversationService.create_group_conversation(
            db, current_user.id, data
        )

    return conversation


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all conversations for current user"""
    conversations = ConversationService.get_user_conversations(db, current_user.id)
    return conversations


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get conversation details"""
    conversation = ConversationService.get_conversation(db, conversation_id, current_user.id)
    message_count = len(conversation.messages)
    return {
        **conversation.__dict__,
        "message_count": message_count,
        "members": conversation.members,
    }


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update conversation (group title)"""
    conversation = ConversationService.update_conversation(
        db, conversation_id, current_user.id, data
    )
    return conversation
