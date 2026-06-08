from uuid import UUID
from datetime import datetime, timezone
from typing import List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc
from fastapi import HTTPException, status

from app.models.user_auth.users import User
from app.models.social.friendships import Friendship
from app.models.social.friend_requests import FriendRequest
from app.schemas.social import FriendRequestCreate, FriendRequestStatusUpdate


class FriendService:
    @staticmethod
    def _serialize_user(user: User) -> Dict[str, Any]:
        if not user:
            return None
        return {
            "id": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
        }

    @staticmethod
    def _serialize_request(req: FriendRequest) -> Dict[str, Any]:
        if not req:
            return None
        return {
            "id": str(req.id),
            "requester_id": str(req.requester_id) if hasattr(req, "requester_id") else None,
            "addressee_id": str(req.addressee_id) if hasattr(req, "addressee_id") else None,
            "status": req.status,
            "created_at": req.created_at,
        }

    @staticmethod
    def send_friend_request(db: Session, requester_id: UUID, data: FriendRequestCreate) -> Dict[str, Any]:
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

        # Check for an existing friend request (any status).
        existing_request = db.query(FriendRequest).filter(
            and_(
                FriendRequest.requester_id == requester_id,
                FriendRequest.addressee_id == data.addressee_id,
            )
        ).first()

        if existing_request:
            # If a pending request already exists, return a 400.
            if existing_request.status == "pending":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Friend request already sent",
                )
            # If a previous request was rejected, reactivate it.
            if existing_request.status == "rejected":
                existing_request.status = "pending"
                existing_request.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(existing_request)
                return FriendService._serialize_request(existing_request)
            # If accepted, treat as already friends.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Friend request already exists",
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
        
        return FriendService._serialize_request(friend_request)

    @staticmethod
    def respond_friend_request(db: Session, request_id: UUID, user_id: UUID, data: FriendRequestStatusUpdate) -> Dict[str, Any]:
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
        friend_request.updated_at = datetime.now(timezone.utc)  # Thay cho utcnow() đã lỗi thời
        
        db.commit()
        db.refresh(friend_request)
        return FriendService._serialize_request(friend_request)

    @staticmethod
    def get_pending_requests(db: Session, user: User) -> List[Dict[str, Any]]:
        """Get pending friend requests for a user"""
        requests = (
            db.query(FriendRequest)
            .options(joinedload(FriendRequest.requester))
            .filter(
                and_(
                    FriendRequest.addressee_id == user.id,
                    FriendRequest.status == "pending"
                )
            )
            .order_by(desc(FriendRequest.created_at))
            .all()
        )

        result = []
        for req in requests:
            data = FriendService._serialize_request(req) or {}
            data["requester"] = (
                FriendService._serialize_user(req.requester) if req.requester else None
            )
            result.append(data)
        return result

    @staticmethod
    def get_friends(db: Session, user: User) -> List[Dict[str, Any]]:
        """Get all friends for current user"""
        try:
            friendships = (
                db.query(Friendship)
                .options(
                    joinedload(Friendship.user_1),
                    joinedload(Friendship.user_2),
                )
                .filter(
                    or_(
                        Friendship.user_id_1 == user.id,
                        Friendship.user_id_2 == user.id,
                    )
                )
                .all()
            )

            result = []
            for friendship in friendships:
                # Determine the friend's ID based on the current user's ID
                friend_id = (
                    friendship.user_id_2
                    if friendship.user_id_1 == user.id
                    else friendship.user_id_1
                )

                friend_obj = (
                    friendship.user_1
                    if friendship.user_id_1 == friend_id
                    else friendship.user_2
                )

                if friend_obj:
                    result.append({
                        "id": str(friendship.id),
                        "user_id_1": str(friendship.user_id_1),
                        "user_id_2": str(friendship.user_id_2),
                        "created_at": friendship.created_at,
                        "friend": FriendService._serialize_user(friend_obj),
                    })
            return result
        except Exception as e:
            print(f"Error in get_friends: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error",
            )