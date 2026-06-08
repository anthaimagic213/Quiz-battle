from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user
from app.models.user_auth.users import User
from app.schemas.social import (
    FriendRequestCreate,
    FriendRequestStatusUpdate,
    FriendRequestResponse,
)
from app.services.friend_service import FriendService

router = APIRouter(
    prefix="/friends",
    tags=["friends"],
)

@router.post("/requests", response_model=FriendRequestResponse, status_code=status.HTTP_201_CREATED)
async def send_friend_request(
    data: FriendRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a friend request to another user"""
    return FriendService.send_friend_request(db, current_user.id, data)


@router.get("/requests/pending", response_model=list)
async def get_pending_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get pending friend requests for current user"""
    return FriendService.get_pending_requests(db, current_user)


@router.post("/requests/{request_id}/respond", response_model=FriendRequestResponse)
async def respond_friend_request(
    request_id: UUID,
    data: FriendRequestStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept or reject a friend request"""
    return FriendService.respond_friend_request(db, request_id, current_user.id, data)


@router.get("/list", response_model=list)
async def get_friends(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all friends for current user"""
    return FriendService.get_friends(db, current_user)
