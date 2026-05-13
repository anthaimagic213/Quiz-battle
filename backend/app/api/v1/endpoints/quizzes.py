from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.services.quiz_service import (
    create_quiz_with_questions,
    delete_quiz as delete_quiz_service,
    get_quiz_detail as get_quiz_detail_service,
    list_quizzes as list_quizzes_service,
    update_quiz_with_questions,
)

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.get("", response_model=list)
def list_quizzes(
    current_user: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_quizzes_service(db, current_user)


@router.get("/{quiz_id}", response_model=dict)
def get_quiz(
    quiz_id: UUID,
    current_user: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_quiz_detail_service(quiz_id, current_user, db)


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_quiz(payload: dict, current_user: UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_quiz_with_questions(payload, current_user, db)


@router.put("/{quiz_id}", response_model=dict)
def update_quiz(
    quiz_id: UUID,
    payload: dict,
    current_user: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_quiz_with_questions(quiz_id, payload, current_user, db)


@router.delete("/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quiz(
    quiz_id: UUID,
    current_user: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_quiz_service(quiz_id, current_user, db)
