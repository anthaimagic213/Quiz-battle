from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user
from app.models.user_auth.users import User
from app.schemas.social import (
    FriendRequestCreate,
    FriendRequestStatusUpdate,
    FriendRequestResponse,
    FriendshipResponse,
)
from app.services.social_service import FriendshipService

# Khai báo Router chuẩn - FastAPI tự động map thành /api/v1/friends
router = APIRouter(
    prefix="/friends",
    tags=["friends"],
)


def _serialize_user(user: User):
    if not user:
        return None
    return {
        "id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
    }


def _serialize_request(req):
    """Gọt sạch dữ liệu SQLAlchemy instance state để tránh lỗi render và lỗi Swagger"""
    if not req:
        return None
    return {
        "id": str(req.id),
        "sender_id": str(req.sender_id) if hasattr(req, "sender_id") else None,
        "receiver_id": str(req.receiver_id) if hasattr(req, "receiver_id") else None,
        "status": req.status,
        "created_at": req.created_at,
    }


# ==================== ENDPOINTS ====================

@router.post("/requests", response_model=FriendRequestResponse, status_code=status.HTTP_201_CREATED)
async def send_friend_request(
    data: FriendRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a friend request to another user -> URL: /api/v1/friends/requests"""
    friend_request = FriendshipService.send_friend_request(db, current_user, data)
    # Serialize để ép kiểu dữ liệu trả về sạch sẽ theo schema
    return _serialize_request(friend_request)


@router.get("/requests/pending", response_model=list)
async def get_pending_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get pending friend requests for current user -> URL: /api/v1/friends/requests/pending"""
    requests = FriendshipService.get_pending_requests(db, current_user)
    return [
        {
            **{k: v for k, v in req.__dict__.items() if k != "_sa_instance_state"},
            "requester": _serialize_user(req.requester) if hasattr(req, "requester") and req.requester else None,
        }
        for req in requests
    ]


@router.post("/requests/{request_id}/respond", response_model=FriendRequestResponse)
async def respond_friend_request(
    request_id: UUID,
    data: FriendRequestStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept or reject a friend request -> URL: /api/v1/friends/requests/{request_id}/respond"""
    friend_request = FriendshipService.respond_friend_request(
        db, request_id, current_user, data
    )
    return _serialize_request(friend_request)


@router.get("/list", response_model=list)
async def get_friends(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all friends for current user -> URL: /api/v1/friends/list"""
    friendships = FriendshipService.get_friends(db, current_user)
    
    from app.models.user_auth.users import User as UserModel
    result = []
    for friendship in friendships:
        friend_id = friendship.user_id_2 if friendship.user_id_1 == current_user else friendship.user_id_1
        friend = db.query(UserModel).filter(UserModel.id == friend_id).first()
        result.append({
            "id": str(friendship.id),
            "user_id_1": str(friendship.user_id_1),
            "user_id_2": str(friendship.user_id_2),
            "created_at": friendship.created_at,
            "friend": _serialize_user(friend),
        })
    return result