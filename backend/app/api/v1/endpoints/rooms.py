from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.services.game_service import (
    create_room as create_room_service,
    get_room as get_room_service,
    get_room_chat as get_room_chat_service,
    get_room_players as get_room_players_service,
    get_room_results as get_room_results_service,
    get_room_state as get_room_state_service,
    get_room_leaderboard as get_room_leaderboard_service,
    join_room as join_room_service,
    leave_room as leave_room_service,
    start_game as start_game_service,
    post_chat_message as post_chat_message_service,
    submit_answer as submit_answer_service,
    next_question as next_question_service,
    finish_game as finish_game_service,
)

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_room(payload: dict, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_room_service(payload, current_user, db)


@router.get("/{room_code}", response_model=dict)
def get_room(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_room_service(room_code, db)


@router.get("/{room_code}/state", response_model=dict)
def get_room_state(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_room_state_service(room_code, db, current_user)


@router.get("/{room_code}/leaderboard", response_model=dict)
def get_room_leaderboard(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_room_leaderboard_service(room_code, db)


@router.post("/{room_code}/join", response_model=dict)
async def join_room(room_code: str, payload: dict, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await join_room_service(room_code, payload, current_user, db)


@router.post("/{room_code}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await leave_room_service(room_code, current_user, db)


@router.get("/{room_code}/players", response_model=list)
def get_room_players(room_code: str, db: Session = Depends(get_db)):
    return get_room_players_service(room_code, db)


@router.post("/{room_code}/start", response_model=dict)
async def start_game(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await start_game_service(room_code, current_user, db)


@router.post("/{room_code}/answers", response_model=dict)
async def submit_answer(room_code: str, payload: dict, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await submit_answer_service(room_code, current_user, payload, db)


@router.post("/{room_code}/next-question", response_model=dict)
async def next_question(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await next_question_service(room_code, current_user, db)


@router.post("/{room_code}/finish", response_model=dict)
async def finish_game(room_code: str, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await finish_game_service(room_code, current_user, db)


@router.get("/{room_code}/results", response_model=list)
def get_room_results(room_code: str, db: Session = Depends(get_db)):
    return get_room_results_service(room_code, db)


@router.get("/{room_code}/chat", response_model=list)
def get_room_chat(room_code: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return get_room_chat_service(room_code, db, limit=limit, offset=offset)


@router.post("/{room_code}/chat", response_model=dict)
async def post_chat_message(room_code: str, payload: dict, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return await post_chat_message_service(room_code, current_user, payload, db)
