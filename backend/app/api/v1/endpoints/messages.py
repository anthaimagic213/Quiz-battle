from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user_obj
from app.models.user_auth.users import User
from app.schemas.social import (
    MessageCreate,
    MessageUpdate,
    MessageResponse,
    MessageListResponse,
    MessageDetailResponse,
)
from app.services.message_service import MessageService

router = APIRouter(
    prefix="/conversations/{conversation_id}/messages",
    tags=["messages"],
)

@router.post("", response_model=MessageDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Create a message in a conversation"""
    return MessageService.create_message(db, conversation_id, current_user.id, data)


@router.get("", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """List messages in a conversation"""
    return MessageService.get_messages_response(db, conversation_id, current_user.id, limit, offset)


@router.put("/{message_id}", response_model=MessageDetailResponse)
async def update_message(
    conversation_id: UUID,
    message_id: UUID,
    data: MessageUpdate,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Update a message (owner only)"""
    return MessageService.update_message(db, message_id, current_user.id, data)


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Delete a message (owner only)"""
    MessageService.delete_message(db, message_id, current_user.id)
    return None


@router.post("/mark-read", response_model=dict)
async def mark_conversation_as_read(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Mark conversation as read (without requiring a message_id)"""
    MessageService.mark_as_read(db, conversation_id, current_user.id)
    return {"message": "Marked as read"}


@router.post("/{message_id}/mark-read", response_model=dict)
async def mark_conversation_read(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """Mark conversation as read"""
    MessageService.mark_as_read(db, conversation_id, current_user.id)
    return {"message": "Marked as read"}
