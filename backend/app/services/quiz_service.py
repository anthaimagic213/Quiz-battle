from uuid import UUID
from datetime import datetime, timezone
from random import choice

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.quiz.answer_options import AnswerOption
from app.models.quiz.questions import Question
from app.models.quiz.quizzes import Quiz
from app.models.game.game_rooms import GameRoom

QUIZ_TITLE_ICONS = [
	"📚",
	"🧠",
	"🎯",
	"🏆",
	"⚡",
	"🌟",
	"🔥",
	"🚀",
	"🎮",
	"💡",
	"🧩",
	"🔬",
	"🌍",
	"🎨",
	"🎵",
]


def _serialize_datetime(value) -> str | None:
	if not value:
		return None

	if value.tzinfo is None:
		value = value.replace(tzinfo=timezone.utc)

	return value.isoformat()


def _title_with_random_icon(title: str) -> str:
	clean_title = title.strip()
	if any(clean_title.startswith(icon) for icon in QUIZ_TITLE_ICONS):
		return clean_title
	return f"{choice(QUIZ_TITLE_ICONS)} {clean_title}"


def _serialize_quiz_summary(quiz: Quiz, question_count: int, time_limit_sum: int) -> dict:
	total_duration_seconds = int(time_limit_sum or 0) + (int(question_count or 0) * 3)
	return {
		"id": str(quiz.id),
		"title": quiz.title,
		"description": quiz.description,
		"is_public": quiz.is_public,
		"is_deleted": bool(getattr(quiz, "is_deleted", False)),
		"created_by": str(quiz.created_by) if quiz.created_by else None,
		"created_at": _serialize_datetime(quiz.created_at),
		"question_count": int(question_count or 0),
		"total_duration_seconds": total_duration_seconds,
	}


def _serialize_quiz_detail(quiz: Quiz) -> dict:
	questions = []
	for question in quiz.questions:
		answer_options = []
		for option in question.answer_options:
			answer_options.append(
				{
					"id": str(option.id),
					"content": option.content,
					"is_correct": option.is_correct,
				}
			)
		questions.append(
			{
				"id": str(question.id),
				"content": question.content,
				"question_type": question.question_type,
				"time_limit": question.time_limit,
				"points": question.points,
				"order_index": question.order_index,
				"answer_options": answer_options,
			}
		)

	return {
		"id": str(quiz.id),
		"title": quiz.title,
		"description": quiz.description,
		"is_public": quiz.is_public,
		"is_deleted": bool(getattr(quiz, "is_deleted", False)),
		"created_by": str(quiz.created_by) if quiz.created_by else None,
		"created_at": _serialize_datetime(quiz.created_at),
		"questions": questions,
	}


def list_quizzes(db: Session, current_user: UUID) -> list:
	quizzes = (
		db.query(
			Quiz,
			func.count(Question.id).label("question_count"),
			func.coalesce(func.sum(Question.time_limit), 0).label("time_limit_sum"),
		)
		.outerjoin(Question, Question.quiz_id == Quiz.id)
		.filter(Quiz.is_deleted.is_(False))
		.filter((Quiz.created_by == current_user) | (Quiz.is_public.is_(True)))
		.group_by(Quiz.id)
		.all()
	)

	return [_serialize_quiz_summary(quiz, question_count, time_limit_sum) for quiz, question_count, time_limit_sum in quizzes]


def search_quizzes(db: Session, current_user: UUID, query: str) -> list:
	q = f"%{query}%"
	quizzes = (
		db.query(
			Quiz,
			func.count(Question.id).label("question_count"),
			func.coalesce(func.sum(Question.time_limit), 0).label("time_limit_sum"),
		)
		.outerjoin(Question, Question.quiz_id == Quiz.id)
		.filter(Quiz.is_deleted.is_(False))
		.filter(((Quiz.created_by == current_user) | (Quiz.is_public.is_(True))) & Quiz.title.ilike(q))
		.group_by(Quiz.id)
		.all()
	)

	return [_serialize_quiz_summary(quiz, question_count, time_limit_sum) for quiz, question_count, time_limit_sum in quizzes]


def get_quiz_detail(quiz_id: UUID, current_user: UUID, db: Session) -> dict:
	quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.is_deleted.is_(False)).first()
	if not quiz:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

	if quiz.created_by != current_user and not quiz.is_public:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to view this quiz")

	return _serialize_quiz_detail(quiz)


def _maybe_ingest_quiz(db: Session, quiz_id) -> None:
    """
    Best-effort ingestion: nếu Qdrant/embedding chưa sẵn sàng thì log warning
    và bỏ qua, không làm fail luồng CRUD quiz.
    """
    try:
        from app.services.ingestion_service import ingest_quiz

        ingest_quiz(db, quiz_id)
    except Exception as e:  # noqa: BLE001
        # Không raise để không phá luồng chính (create/update/delete quiz)
        # Có thể bật flag fail-fast sau nếu muốn.
        import logging

        logging.getLogger(__name__).warning(
            "Ingestion hook failed for quiz %s: %s", quiz_id, e
        )


def _maybe_remove_quiz_from_index(quiz_id) -> None:
    try:
        from app.services.ingestion_service import remove_quiz_from_index

        remove_quiz_from_index(str(quiz_id))
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Remove-from-index failed for quiz %s: %s", quiz_id, e
        )


def create_quiz_with_questions(payload: dict, current_user: UUID, db: Session) -> dict:
	title = payload.get("title")
	if not title:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing title")

	quiz = Quiz(
		title=_title_with_random_icon(title),
		description=payload.get("description"),
		is_public=payload.get("is_public", False),
		created_by=current_user,
	)
	db.add(quiz)
	db.commit()
	db.refresh(quiz)

	questions_data = payload.get("questions", [])
	if questions_data:
		try:
			for question_payload in questions_data:
				question = Question(
					quiz_id=quiz.id,
					content=question_payload.get("content"),
					question_type=question_payload.get("question_type"),
					time_limit=question_payload.get("time_limit"),
					points=question_payload.get("points", 100),
					order_index=question_payload.get("order_index"),
				)
				db.add(question)
				db.flush()

				for option_payload in question_payload.get("answer_options", []):
					option = AnswerOption(
						question_id=question.id,
						content=option_payload.get("content"),
						is_correct=option_payload.get("is_correct", False),
					)
					db.add(option)

			db.commit()
		except Exception:
			db.rollback()
			raise

	db.refresh(quiz)

	# Hook: ingest vào Qdrant (best-effort)
	_maybe_ingest_quiz(db, quiz.id)

	return {
		"id": str(quiz.id),
		"title": quiz.title,
		"description": quiz.description,
		"is_public": quiz.is_public,
		"created_by": str(quiz.created_by) if quiz.created_by else None,
		"created_at": _serialize_datetime(quiz.created_at),
	}


def update_quiz_with_questions(quiz_id: UUID, payload: dict, current_user: UUID, db: Session) -> dict:
	quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.is_deleted.is_(False)).first()
	if not quiz:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

	if quiz.created_by != current_user:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to edit this quiz")

	title = payload.get("title")
	if not title:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing title")

	quiz.title = title
	quiz.description = payload.get("description")
	quiz.is_public = payload.get("is_public", False)

	questions_data = payload.get("questions", [])
	if questions_data:
		try:
			db.query(Question).filter(Question.quiz_id == quiz_id).delete(synchronize_session=False)
			db.flush()

			for question_payload in questions_data:
				question = Question(
					quiz_id=quiz_id,
					content=question_payload.get("content"),
					question_type=question_payload.get("question_type"),
					time_limit=question_payload.get("time_limit"),
					points=question_payload.get("points", 100),
					order_index=question_payload.get("order_index"),
				)
				db.add(question)
				db.flush()

				for option_payload in question_payload.get("answer_options", []):
					option = AnswerOption(
						question_id=question.id,
						content=option_payload.get("content"),
						is_correct=option_payload.get("is_correct", False),
					)
					db.add(option)

			db.commit()
		except Exception:
			db.rollback()
			raise
	else:
		db.commit()

		db.refresh(quiz)

	# Hook: re-ingest sau update (best-effort)
	_maybe_ingest_quiz(db, quiz_id)

	return {
		"id": str(quiz.id),
		"title": quiz.title,
		"description": quiz.description,
		"is_public": quiz.is_public,
		"is_deleted": bool(getattr(quiz, "is_deleted", False)),
		"created_by": str(quiz.created_by) if quiz.created_by else None,
		"created_at": _serialize_datetime(quiz.created_at),
	}


def delete_quiz(quiz_id: UUID, current_user: UUID, db: Session) -> None:
	quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.is_deleted.is_(False)).first()
	if not quiz:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

	if quiz.created_by != current_user:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to delete this quiz")

		has_game_history = db.query(GameRoom.id).filter(GameRoom.quiz_id == quiz.id).first() is not None
	if has_game_history:
		quiz.is_deleted = True
		quiz.is_public = False
		quiz.deleted_at = datetime.now(timezone.utc)
		db.commit()
		# Hook: dọn khỏi index khi soft-delete
		_maybe_ingest_quiz(db, quiz_id)
		return

	db.delete(quiz)
	db.commit()
	# Hook: dọn khỏi index khi hard-delete
	_maybe_remove_quiz_from_index(quiz_id)
