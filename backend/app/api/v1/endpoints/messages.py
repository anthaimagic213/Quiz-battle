from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID

from app.api.dependencies import get_db, get_current_user_obj
from app.models.user_auth.users import User
from app.models.social.conversation_members import ConversationMember
from app.schemas.social import (
    MessageCreate,
    MessageUpdate,
    MessageResponse,
    MessageListResponse,
    MessageDetailResponse,
)
from app.services.message_service import MessageService
from app.services.search_service import search_messages
from app.services.ai_orchestrator import run_ai_orchestrator
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/conversations/{conversation_id}/messages",
    tags=["messages"],
)

@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """
    Create a message in a conversation.
    
    CHỈ trigger AI khi message bắt đầu với '@ai' (case-insensitive).
    Ví dụ: '@ai tìm quiz về lịch sử' → trigger AI
           'Xin chào' → không trigger AI (chỉ lưu message)
           '@Ai top 5 user' → trigger AI
    
    Returns user message + AI response (nếu được trigger).
    """
    # 1. Check if message should trigger AI (BẮT BUỘC có @ai ở đầu)
    raw_content = data.content.strip()
    content_lower = raw_content.lower()
    
    # Patterns được trigger: @ai, @bot (case-insensitive) + space/tab/newline
    trigger_patterns = ['@ai ', '@ai\n', '@ai\t', '@bot ', '@bot\n', '@bot\t']
    trigger_ai = any(content_lower.startswith(p) for p in trigger_patterns)
    
    # Chuẩn hóa nội dung: loại bỏ @ai/@bot prefix khi gửi cho AI
    if trigger_ai:
        # Tìm prefix match (giữ nguyên case cho content)
        for prefix in ['@ai', '@bot', '@AI', '@AI ', '@Bot', '@BOT']:
            if raw_content.startswith(prefix):
                cleaned_content = raw_content[len(prefix):].lstrip(' \t\n')
                break
        else:
            cleaned_content = raw_content
    else:
        cleaned_content = raw_content
    
    # 2. Create user message (lưu content GỐC, không strip prefix)
    user_message = MessageService.create_message(db, conversation_id, current_user.id, data)
    
    if not trigger_ai:
        # Không có @ai → chỉ lưu message, KHÔNG gọi AI
        return {
            "user_message": user_message,
            "ai_response": None,
            "triggered_ai": False,
            "reason": "Message không bắt đầu với @ai",
        }
    
    # 3. Get recent history for context
    try:
        messages_response = MessageService.get_messages_response(
            db, conversation_id, current_user.id, limit=10, offset=0
        )
        recent_history = [
            {
                "sender_type": msg.get("sender_type", "user"),
                "content": msg.get("content", ""),
            }
            for msg in messages_response.get("items", [])
        ]
    except Exception as e:
        logger.warning(f"Failed to get recent history: {e}")
        recent_history = []
    
    # 4. Run AI orchestrator với content đã strip prefix
    try:
        ai_result = run_ai_orchestrator(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            user_message=cleaned_content,  # Dùng content đã strip @ai
            user_message_id=UUID(user_message["id"]),
            recent_history=recent_history,
        )
        
        return {
            "user_message": user_message,
            "ai_response": {
                "answer": ai_result["answer"],
                "intent": ai_result["intent"],
                "confidence": ai_result["confidence"],
                "ai_message_id": str(ai_result["ai_message_id"]) if ai_result.get("ai_message_id") else None,
                "timings": ai_result["timings"],
                "error": ai_result.get("error"),
            },
            "triggered_ai": True,
        }
    
    except Exception as e:
        logger.exception(f"AI orchestrator failed: {e}")
        return {
            "user_message": user_message,
            "ai_response": {
                "answer": "Xin lỗi, tôi đang gặp sự cố kỹ thuật. Bạn thử lại sau nhé.",
                "error": str(e),
            },
            "triggered_ai": True,
        }


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


@router.get("/search", response_model=list)
async def search_messages_endpoint(
    conversation_id: UUID,
    q: str = Query(..., min_length=1, description="Câu truy vấn ngôn ngữ tự nhiên"),
    top_k: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """
    Semantic search các message trong 1 conversation.
    Chỉ member của conversation mới được search.
    Dùng để truy hồi context cho AI reply (Phase 3+).
    """
    member = (
        db.query(ConversationMember)
        .filter(
            and_(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.id,
            )
        )
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this conversation",
        )
    return search_messages(query=q, conversation_id=str(conversation_id), top_k=top_k)
