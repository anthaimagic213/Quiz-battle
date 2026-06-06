from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user
from app.models.user_auth.users import User
from app.schemas.social import (
    MessageCreate,
    MessageUpdate,
    MessageResponse,
    MessageDetailResponse,
    MessageListResponse,
)
from app.services.social_service import MessageService, ConversationService

router = APIRouter(
    prefix="/conversations/{conversation_id}/messages",
    tags=["messages"],
)


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a message in a conversation"""
    message = MessageService.create_message(db, conversation_id, current_user.id, data)
    return message


@router.get("", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List messages in a conversation"""
    messages, total = MessageService.get_messages(db, conversation_id, current_user.id, limit, offset)

    message_details = []
    for msg in messages:
        detail = MessageDetailResponse(
            **msg.__dict__,
            sender_username=msg.sender.username if msg.sender else None,
            sender_avatar_url=msg.sender.avatar_url if msg.sender else None,
        )
        message_details.append(detail)

    return MessageListResponse(
        messages=message_details,
        total=total,
        page=offset // limit + 1,
        page_size=limit,
    )


@router.put("/{message_id}", response_model=MessageResponse)
async def update_message(
    conversation_id: UUID,
    message_id: UUID,
    data: MessageUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a message (owner only)"""
    message = MessageService.update_message(db, message_id, current_user.id, data)
    return message


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a message (owner only)"""
    MessageService.delete_message(db, message_id, current_user.id)
    return None


@router.post("/{message_id}/mark-read", response_model=MessageResponse)
async def mark_conversation_read(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark conversation as read"""
    MessageService.mark_as_read(db, conversation_id, current_user.id)
    return {"message": "Marked as read"}
