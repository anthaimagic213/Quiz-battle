from fastapi import Depends, Header
from uuid import UUID
from app.core.security import decode_token
from app.core.exceptions import InvalidToken
from app.db.session import get_db

async def get_current_user(authorization: str = Header(None)) -> UUID:
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
