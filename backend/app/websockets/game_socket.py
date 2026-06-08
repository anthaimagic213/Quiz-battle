import asyncio
import json
from uuid import UUID
from typing import Dict

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db, SessionLocal
from app.models.game.chat_messages import ChatMessage
from app.models.game.game_rooms import GameRoom
from app.models.game.room_players import RoomPlayer
from app.models.user_auth.users import User
from app.services.redis_manager import redis_manager
from app.websockets.connection_manager import manager

router = APIRouter()
HOST_DISCONNECT_GRACE_SECONDS = 15
pending_room_close_tasks: Dict[str, asyncio.Task] = {}


def _serialize_player(player: RoomPlayer) -> dict:
    return {
        "id": str(player.id),
        "room_id": str(player.room_id),
        "user_id": str(player.user_id),
        "display_name": player.display_name,
        "score": player.score,
    }


def _serialize_room_state(room: GameRoom, db: Session) -> dict:
    players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
    return {
        "room_code": room.room_code,
        "host_id": str(room.host_id) if room.host_id else None,
        "players": [_serialize_player(player) for player in players],
        "player_count": len(players),
    }


def _cancel_pending_close_if_exists(room_code: str) -> None:
    task = pending_room_close_tasks.pop(room_code, None)
    if task and not task.done():
        task.cancel()


def _serialize_chat_message(message: ChatMessage, user: User | None) -> dict:
    return {
        "id": str(message.id),
        "room_id": str(message.room_id),
        "user_id": str(message.user_id),
        "message": message.message,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "user": {
            "id": str(user.id) if user else None,
            "username": user.username if user else None,
        },
    }


async def _handle_chat_message(room_code: str, current_user_id: UUID, payload: dict, db: Session) -> None:
    cached_meta = redis_manager.get_room_meta(room_code)
    if cached_meta:
        if not cached_meta.get("chat_enabled"):
            return

        player = redis_manager.get_player(room_code, str(current_user_id))
        if not player or player.get("status") == "LEFT":
            return

        message_text = str(payload.get("message", "")).strip()
        if not message_text or len(message_text) > 500:
            return

        message = ChatMessage(
            room_id=UUID(str(cached_meta.get("id"))),
            user_id=current_user_id,
            message=message_text,
        )
        db.add(message)
        db.commit()
        db.refresh(message)

        await manager.broadcast(
            room_code,
            {
                "type": "CHAT_MESSAGE",
                "data": {
                    "id": str(message.id),
                    "room_id": str(message.room_id),
                    "user_id": str(message.user_id),
                    "message": message.message,
                    "created_at": message.created_at,
                    "updated_at": message.updated_at,
                    "user": {
                        "id": str(current_user_id),
                        "username": player.get("display_name"),
                    },
                },
            },
        )
        return

    room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
    if not room:
        return

    if not room.chat_enabled:
        return

    player = db.query(RoomPlayer).filter(
        RoomPlayer.room_id == room.id,
        RoomPlayer.user_id == current_user_id,
    ).first()
    if not player:
        return

    message_text = str(payload.get("message", "")).strip()
    if not message_text or len(message_text) > 500:
        return

    message = ChatMessage(
        room_id=room.id,
        user_id=current_user_id,
        message=message_text,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    user = db.query(User).filter(User.id == current_user_id).first()
    await manager.broadcast(
        room_code,
        {
            "type": "CHAT_MESSAGE",
            "data": _serialize_chat_message(message, user),
        },
    )


async def _close_room_if_host_not_reconnected(room_code: str, host_user_id: UUID) -> None:
    try:
        await asyncio.sleep(HOST_DISCONNECT_GRACE_SECONDS)

        # Host already reconnected within grace period.
        if manager.has_user_connection(room_code, str(host_user_id)):
            return

        db = SessionLocal()
        try:
            room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
            if not room:
                return

            # Keep active or finished games alive even if the host is offline.
            if room.status in ("PLAYING", "FINISHED"):
                return

            if room.host_id != host_user_id:
                return

            room_state = _serialize_room_state(room, db)
            await manager.broadcast(room_code, {
                "type": "ROOM_CLOSED",
                "data": {
                    **room_state,
                    "reason": "HOST_LEFT",
                    "message": "Host đã mất kết nối quá lâu, phòng đã đóng.",
                },
            })

            db.delete(room)
            db.commit()
        finally:
            db.close()
    except asyncio.CancelledError:
        # Host reconnected and pending close was cancelled.
        return
    finally:
        pending_room_close_tasks.pop(room_code, None)


@router.websocket("/ws/game/{room_code}")
async def game_socket(websocket: WebSocket, room_code: str, db: Session = Depends(get_db)):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=4401)
        return

    try:
        current_user_id = UUID(payload["sub"])
    except ValueError:
        await websocket.close(code=4401)
        return

    cached_meta = redis_manager.get_room_meta(room_code)
    if cached_meta:
        if cached_meta.get("host_id") == str(current_user_id):
            _cancel_pending_close_if_exists(room_code)

        if cached_meta.get("status") in ("PLAYING", "FINISHED"):
            player = redis_manager.get_player(room_code, str(current_user_id))
            if not player and cached_meta.get("host_id") != str(current_user_id):
                await websocket.close(code=4403)
                return
    else:
        room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
        if room and room.host_id == current_user_id:
            _cancel_pending_close_if_exists(room_code)

        if room and room.status in ("PLAYING", "FINISHED"):
            player = db.query(RoomPlayer).filter(
                RoomPlayer.room_id == room.id,
                RoomPlayer.user_id == current_user_id,
            ).first()

            if not player:
                await websocket.close(code=4403)
                return

    await manager.connect(room_code, str(current_user_id), websocket)
    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                parsed = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event_type = parsed.get("type")
            data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
            if event_type == "CHAT_MESSAGE":
                await _handle_chat_message(room_code, current_user_id, data, db)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room_code, str(current_user_id), websocket)
        room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
        if not room:
            return

        if room.status == "FINISHED":
            return

        if room.host_id == current_user_id:
            if manager.has_user_connection(room_code, str(current_user_id)):
                return

            _cancel_pending_close_if_exists(room_code)
            pending_room_close_tasks[room_code] = asyncio.create_task(
                _close_room_if_host_not_reconnected(room_code, current_user_id)
            )
            return

