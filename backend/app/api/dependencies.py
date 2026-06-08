from fastapi import Depends, Header
from sqlalchemy.orm import Session
from uuid import UUID
from app.core.security import decode_token
from app.core.exceptions import InvalidToken
from app.db.session import get_db
from app.models.user_auth.users import User


async def get_current_user(authorization: str = Header(None)) -> UUID:
    """Resolve the current access token to a user_id (UUID)."""
    if not authorization:
        raise InvalidToken("Missing authorization header")

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise InvalidToken("Invalid authentication scheme")
    except ValueError:
        raise InvalidToken("Invalid authorization header format")

    payload = decode_token(token)

    if payload is None:
        raise InvalidToken("Could not validate credentials")

    if payload.get("type") != "access":
        raise InvalidToken("Invalid token type")

    user_id: str = payload.get("sub")
    if user_id is None:
        raise InvalidToken("Could not validate credentials")

    try:
        return UUID(user_id)
    except ValueError:
        raise InvalidToken("Invalid user ID in token")


async def get_current_user_obj(
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user),
) -> User:
    """Resolve the current access token to a full User ORM object."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise InvalidToken("User not found")
    return user

