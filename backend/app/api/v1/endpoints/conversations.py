from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user, get_current_user_obj
from app.models.user_auth.users import User
from app.schemas.social import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationDetailResponse,
    ConversationMemberResponse,
    ConversationWithMemberResponse,
)
from app.services.conversation_service import ConversationService

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
)


@router.post("/direct/{other_user_id}", response_model=ConversationWithMemberResponse, status_code=status.HTTP_201_CREATED)
async def create_or_get_direct_conversation(
    other_user_id: UUID,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Create or get the 1-1 conversation between the current user and another user.

    Returns the conversation plus a snapshot of the other user's basic profile so
    the client can render the chat header without a second request.
    """
    return ConversationService.create_or_get_direct_with_member(
        db, current_user.id, other_user_id
    )


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Create a new conversation (direct or group)"""
    return ConversationService.create_conversation(db, current_user.id, data)


@router.get("", response_model=list[ConversationWithMemberResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """List all conversations for current user, with the other member's profile for direct chats."""
    return ConversationService.list_user_conversations_with_member(db, current_user.id)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Get conversation details"""
    return ConversationService.get_conversation_details(db, conversation_id, current_user.id)


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Update conversation (group title)"""
    return ConversationService.update_conversation(db, conversation_id, current_user.id, data)
