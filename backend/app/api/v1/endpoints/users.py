from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.user_auth.users import User

router = APIRouter(prefix="/users", tags=["users"])


def _serialize_user(user: User):
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@router.get("", response_model=list)
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [_serialize_user(user) for user in users]


@router.get("/me", response_model=dict)
def read_me(current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _serialize_user(user)


@router.get("/{user_id}", response_model=dict)
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _serialize_user(user)
