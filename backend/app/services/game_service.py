from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.game.chat_messages import ChatMessage
from app.models.game.game_questions import GameQuestion
from app.models.game.game_rooms import GameRoom
from app.models.game.room_players import RoomPlayer
from app.models.game.player_answers import PlayerAnswer
from app.models.game.game_results import GameResult
from app.models.game.kicked_players import KickedPlayer
from app.models.quiz.quizzes import Quiz
from app.models.quiz.questions import Question
from app.models.quiz.answer_options import AnswerOption
from app.models.user_auth.users import User
from app.services.redis_manager import redis_manager
from app.websockets.game_socket import manager


def _serialize_room(room: GameRoom) -> dict:
	return {
		"id": str(room.id),
		"room_code": room.room_code,
		"host_id": str(room.host_id) if room.host_id else None,
		"quiz_id": str(room.quiz_id),
		"status": room.status,
		"started_at": room.started_at,
		"ended_at": room.ended_at,
	}


def _serialize_player(player: RoomPlayer) -> dict:
	return {
		"id": str(player.id),
		"room_id": str(player.room_id),
		"user_id": str(player.user_id),
		"display_name": player.display_name,
		"score": player.score,
	}


def _serialize_chat_message(message: ChatMessage) -> dict:
	return {
		"id": str(message.id),
		"room_id": str(message.room_id),
		"user_id": str(message.user_id),
		"message": message.message,
		"created_at": message.created_at,
		"updated_at": message.updated_at,
		"user": {
			"id": str(message.user.id) if message.user else None,
			"username": message.user.username if message.user else None,
		},
	}


def _serialize_answer_option(option: AnswerOption) -> dict:
	return {
		"id": str(option.id),
		"question_id": str(option.question_id),
		"content": option.content,
	}


def _serialize_answer_option_for_cache(option: AnswerOption) -> dict:
	return {
		"id": str(option.id),
		"question_id": str(option.question_id),
		"content": option.content,
		"is_correct": bool(option.is_correct),
	}


def _serialize_question(question: Question) -> dict:
	return {
		"id": str(question.id),
		"quiz_id": str(question.quiz_id),
		"content": question.content,
		"question_type": question.question_type,
		"time_limit": question.time_limit,
		"points": question.points,
		"order_index": question.order_index,
		"answer_options": [_serialize_answer_option(option) for option in question.answer_options],
	}


def _serialize_question_for_cache(question: Question, question_order: int) -> dict:
	correct_option = next((option for option in question.answer_options if option.is_correct), None)
	return {
		"id": str(question.id),
		"quiz_id": str(question.quiz_id),
		"content": question.content,
		"question_type": question.question_type,
		"time_limit": question.time_limit,
		"points": question.points,
		"order_index": question.order_index,
		"question_order": int(question_order),
		"correct_option_id": str(correct_option.id) if correct_option else None,
		"answer_options": [_serialize_answer_option_for_cache(option) for option in question.answer_options],
	}


def _question_from_cache(question_payload: dict | None) -> dict | None:
	if not question_payload:
		return None
	return {
		"id": question_payload.get("id"),
		"quiz_id": question_payload.get("quiz_id"),
		"content": question_payload.get("content"),
		"question_type": question_payload.get("question_type"),
		"time_limit": question_payload.get("time_limit"),
		"points": question_payload.get("points"),
		"order_index": question_payload.get("order_index"),
		"answer_options": [
			{
				"id": option.get("id"),
				"question_id": option.get("question_id"),
				"content": option.get("content"),
			}
			for option in question_payload.get("answer_options", [])
		],
	}


def _room_payload_from_room(room: GameRoom) -> dict:
	return {
		"id": str(room.id),
		"room_code": room.room_code,
		"host_id": str(room.host_id) if room.host_id else None,
		"quiz_id": str(room.quiz_id),
		"status": room.status,
		"max_players": room.max_players,
		"shuffle_questions": room.shuffle_questions,
		"chat_enabled": room.chat_enabled,
		"current_question_order": room.current_question_order,
		"started_at": room.started_at.isoformat() if room.started_at else None,
		"ended_at": room.ended_at.isoformat() if room.ended_at else None,
	}


def _quiz_payload_from_quiz(quiz: Quiz) -> dict:
	return {
		"id": str(quiz.id),
		"title": quiz.title,
		"description": quiz.description,
		"created_by": str(quiz.created_by) if quiz.created_by else None,
	}


def _player_payload_from_room_player(player: RoomPlayer) -> dict:
	return {
		"id": str(player.id),
		"room_id": str(player.room_id),
		"user_id": str(player.user_id),
		"display_name": player.display_name,
		"score": int(player.score or 0),
		"current_question_order": int(player.current_question_order or 0),
		"status": "ACTIVE",
	}


def _player_payload_from_cache(player_payload: dict) -> dict:
	return {
		"id": player_payload.get("id"),
		"room_id": player_payload.get("room_id"),
		"user_id": player_payload.get("user_id"),
		"display_name": player_payload.get("display_name"),
		"score": int(player_payload.get("score") or 0),
		"current_question_order": int(player_payload.get("current_question_order") or 0),
		"status": player_payload.get("status") or "ACTIVE",
	}


def _calculate_points(
	is_correct: bool,
	response_time: float | int | None,
	question_points: int | None,
	question_time_limit: float | int | None,
) -> int:
	if not is_correct:
		return 0

	base_points = int(question_points or 0)
	if base_points <= 0:
		return 0

	time_taken = float(response_time or 0)
	if time_taken <= 3:
		return base_points

	max_time = float(question_time_limit or 0)
	if max_time > 3:
		# Keep scoring bounded by the question timer for fairer calculation.
		time_taken = min(time_taken, max_time)

	# After 3s, points still decrease inversely with time but with a gentler slope.
	inverse_multiplier = min(1.0,1 - time_taken / question_time_limit + 0.1) if question_time_limit and question_time_limit > 0 else 1.0
	return max(int(base_points * inverse_multiplier), 1)


def _build_live_score_map(room: GameRoom, db: Session) -> dict[str, int]:
	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	score_map = {str(player.user_id): 0 for player in players}

	answers = (
		db.query(PlayerAnswer, Question)
		.join(Question, Question.id == PlayerAnswer.question_id)
		.filter(PlayerAnswer.room_id == room.id)
		.all()
	)

	for answer, question in answers:
		user_id = str(answer.user_id)
		score_map[user_id] = score_map.get(user_id, 0) + _calculate_points(
			answer.is_correct,
			answer.response_time,
			question.points,
			question.time_limit,
		)

	return score_map


def _update_user_stats_compat(db: Session, user_id: UUID, score: int, is_winner: bool, has_wins_column: bool) -> None:
	"""Update user_stats without assuming the DB always has the wins column."""
	if has_wins_column:
		row = db.execute(
			text(
				"""
				SELECT total_games, total_score, wins
				FROM user_stats
				WHERE user_id = CAST(:user_id AS uuid)
				"""
			),
			{"user_id": str(user_id)},
		).mappings().first()
	else:
		row = db.execute(
			text(
				"""
				SELECT total_games, total_score
				FROM user_stats
				WHERE user_id = CAST(:user_id AS uuid)
				"""
			),
			{"user_id": str(user_id)},
		).mappings().first()

	if row:
		total_games = int(row["total_games"] or 0) + 1
		total_score = int(row["total_score"] or 0) + score
		avg_score = total_score / total_games if total_games else 0.0

		if has_wins_column:
			wins = int(row["wins"] or 0) + (1 if is_winner else 0)
			db.execute(
				text(
					"""
					UPDATE user_stats
					SET total_games = :total_games,
						total_score = :total_score,
						avg_score = :avg_score,
						wins = :wins,
						updated_at = NOW()
					WHERE user_id = CAST(:user_id AS uuid)
					"""
				),
				{
					"user_id": str(user_id),
					"total_games": total_games,
					"total_score": total_score,
					"avg_score": avg_score,
					"wins": wins,
				},
			)
		else:
			db.execute(
				text(
					"""
					UPDATE user_stats
					SET total_games = :total_games,
						total_score = :total_score,
						avg_score = :avg_score,
						updated_at = NOW()
					WHERE user_id = CAST(:user_id AS uuid)
					"""
				),
				{
					"user_id": str(user_id),
					"total_games": total_games,
					"total_score": total_score,
					"avg_score": avg_score,
				},
			)
		return

	if has_wins_column:
		db.execute(
			text(
				"""
				INSERT INTO user_stats (user_id, total_games, total_score, avg_score, wins, created_at, updated_at)
				VALUES (CAST(:user_id AS uuid), :total_games, :total_score, :avg_score, :wins, NOW(), NOW())
				"""
			),
			{
				"user_id": str(user_id),
				"total_games": 1,
				"total_score": score,
				"avg_score": float(score),
				"wins": 1 if is_winner else 0,
			},
		)
	else:
		db.execute(
			text(
				"""
				INSERT INTO user_stats (user_id, total_games, total_score, avg_score, created_at, updated_at)
				VALUES (CAST(:user_id AS uuid), :total_games, :total_score, :avg_score, NOW(), NOW())
				"""
			),
			{
				"user_id": str(user_id),
				"total_games": 1,
				"total_score": score,
				"avg_score": float(score),
			},
		)


def _serialize_room_state(room: GameRoom, db: Session) -> dict:
	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	return {
		"room": _serialize_room(room),
		"players": [_serialize_player(player) for player in players],
		"player_count": len(players),
	}


def _get_active_question(room: GameRoom, db: Session, current_question_order: int) -> tuple[dict | None, int]:
	cached_question = redis_manager.get_question(room.room_code, current_question_order) if redis_manager.room_exists(room.room_code) else None
	if cached_question:
		return _question_from_cache(cached_question), current_question_order

	game_questions = sorted(list(room.game_questions or []), key=lambda game_question: game_question.question_order or 0)
	if not game_questions:
		return None, current_question_order

	if current_question_order < 1:
		current_question_order = 1

	current_game_question = None
	for game_question in game_questions:
		if game_question.question_order == current_question_order:
			current_game_question = game_question
			break

	if current_game_question is None:
		current_game_question = game_questions[0]
		current_question_order = current_game_question.question_order or 1

	if current_game_question.question:
		return _serialize_question(current_game_question.question), current_question_order

	return None, current_question_order


def get_room_state(room_code: str, db: Session, current_user: UUID = None) -> dict:
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		cached_players = redis_manager.get_room_players(room_code, include_left=False)
		cached_scores = redis_manager.get_room_scores(room_code)
		current_question_order = 1
		if current_user and cached_meta.get("status") == "PLAYING":
			current_player = redis_manager.get_player(room_code, str(current_user))
			if current_player:
				current_question_order = int(current_player.get("current_question_order") or 1)
		elif cached_meta.get("status") == "PLAYING":
			current_question_order = int(cached_meta.get("current_question_order") or 1)

		current_question = None
		if cached_meta.get("status") == "PLAYING":
			current_question = _question_from_cache(redis_manager.get_question(room_code, current_question_order))
		elif cached_meta.get("status") == "WAITING":
			cached_questions = redis_manager.get_room_questions(room_code)
			if cached_questions:
				first_order = sorted(cached_questions.keys())[0]
				current_question = _question_from_cache(cached_questions[first_order])

		leaderboard = redis_manager.get_leaderboard(room_code)
		question_count = redis_manager.get_total_questions(room_code)
		room_payload = {
			"id": cached_meta.get("id"),
			"room_code": cached_meta.get("room_code"),
			"host_id": cached_meta.get("host_id"),
			"quiz_id": cached_meta.get("quiz_id"),
			"status": cached_meta.get("status"),
			"max_players": cached_meta.get("max_players"),
			"shuffle_questions": cached_meta.get("shuffle_questions"),
			"chat_enabled": cached_meta.get("chat_enabled"),
			"current_question_order": cached_meta.get("current_question_order"),
			"started_at": cached_meta.get("started_at"),
			"ended_at": cached_meta.get("ended_at"),
		}
		quiz_payload = {
			"id": cached_meta.get("quiz_id"),
			"title": cached_meta.get("title"),
			"description": cached_meta.get("description"),
			"question_count": question_count,
			"created_by": cached_meta.get("created_by"),
		}
		return {
			"room": room_payload,
			"quiz": quiz_payload,
			"players": cached_players,
			"player_count": len(cached_players),
			"settings": {
				"max_players": cached_meta.get("max_players"),
				"shuffle_questions": cached_meta.get("shuffle_questions"),
				"chat_enabled": cached_meta.get("chat_enabled"),
				"current_question_order": current_question_order,
			},
			"game_state": {
				"status": cached_meta.get("status"),
				"current_question_order": current_question_order,
				"current_question": current_question,
				"total_questions": question_count,
				"leaderboard": leaderboard,
			},
		}

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	quiz = room.quiz
	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	serialized_players = [_serialize_player(player) for player in players]

	quiz_questions = sorted(list(quiz.questions or []), key=lambda question: question.order_index or 0)
	game_questions = sorted(list(room.game_questions or []), key=lambda game_question: game_question.question_order or 0)
	
	# Get current_question_order for current user (independent progress)
	current_question_order = 1
	if current_user and room.status == "PLAYING":
		current_player = db.query(RoomPlayer).filter(
			RoomPlayer.room_id == room.id,
			RoomPlayer.user_id == current_user
		).first()
		if current_player:
			current_question_order = current_player.current_question_order or 1
	elif room.status == "PLAYING":
		current_question_order = room.current_question_order or 1

	current_question = None
	if room.status == "PLAYING":
		current_question, current_question_order = _get_active_question(room, db, current_question_order)
	elif room.status == "WAITING" and quiz_questions:
		current_question = _serialize_question(quiz_questions[0])

	leaderboard = _get_leaderboard(room, db)

	return {
		"room": _serialize_room(room),
		"quiz": {
			"id": str(quiz.id),
			"title": quiz.title,
			"description": quiz.description,
			"question_count": len(quiz_questions),
			"created_by": str(quiz.created_by) if quiz.created_by else None,
		},
		"players": serialized_players,
		"player_count": len(serialized_players),
		"settings": {
			"max_players": room.max_players,
			"shuffle_questions": room.shuffle_questions,
			"chat_enabled": room.chat_enabled,
			"current_question_order": current_question_order,
		},
		"game_state": {
			"status": room.status,
			"current_question_order": current_question_order,
			"current_question": current_question,
			"total_questions": len(game_questions) if game_questions else len(quiz_questions),
			"leaderboard": leaderboard,
		},
	}


def _build_room_code() -> str:
	return uuid4().hex[:6].upper()


def create_room(payload: dict, current_user: UUID, db: Session) -> dict:
	quiz_id = payload.get("quiz_id")
	if not quiz_id:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing quiz_id")

	quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
	if not quiz:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

	if not quiz.is_public and quiz.created_by != current_user:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to use this quiz")

	room = GameRoom(
		room_code=_build_room_code(),
		host_id=current_user,
		quiz_id=quiz.id,
		status="WAITING",
		max_players=payload.get("max_players", 30),
		shuffle_questions=payload.get("shuffle_questions", True),
		chat_enabled=payload.get("chat_enabled", True),
	)
	db.add(room)
	db.commit()
	db.refresh(room)

	user = db.query(User).filter(User.id == current_user).first()
	host_player = RoomPlayer(
		room_id=room.id,
		user_id=current_user,
		display_name=user.username if user else "Host",
		score=0,
		current_question_order=0,  # Not started yet
	)
	db.add(host_player)
	db.commit()

	return _serialize_room(room)


def get_room(room_code: str, db: Session) -> dict:
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		cached_players = redis_manager.get_room_players(room_code, include_left=False)
		cached_questions = redis_manager.get_room_questions(room_code)
		question_count = len(cached_questions)
		time_limit_sum = sum(int(question.get("time_limit") or 0) for question in cached_questions.values())
		total_duration_seconds = time_limit_sum + (question_count * 3)
		total_duration_minutes = total_duration_seconds // 60
		total_duration_remaining = total_duration_seconds % 60
		return {
			"id": cached_meta.get("id"),
			"room_code": cached_meta.get("room_code"),
			"host_id": cached_meta.get("host_id"),
			"status": cached_meta.get("status"),
			"created_at": cached_meta.get("created_at"),
			"started_at": cached_meta.get("started_at"),
			"ended_at": cached_meta.get("ended_at"),
			"quiz": {
				"id": cached_meta.get("quiz_id"),
				"title": cached_meta.get("title"),
				"description": cached_meta.get("description"),
				"question_count": question_count,
				"total_duration_seconds": total_duration_seconds,
				"total_duration_formatted": f"~{total_duration_minutes}m {total_duration_remaining}s" if total_duration_minutes > 0 else f"~{total_duration_remaining}s",
				"created_by": cached_meta.get("created_by"),
			},
			"players": cached_players,
			"player_count": len(cached_players),
			"settings": {
				"max_players": cached_meta.get("max_players"),
				"shuffle_questions": cached_meta.get("shuffle_questions"),
				"chat_enabled": cached_meta.get("chat_enabled"),
				"current_question_order": cached_meta.get("current_question_order"),
			},
		}

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	quiz = room.quiz
	question_count = len(quiz.questions) if quiz.questions else 0
	time_limit_sum = sum(question.time_limit or 0 for question in quiz.questions) if quiz.questions else 0
	total_duration_seconds = time_limit_sum + (question_count * 3)
	total_duration_minutes = total_duration_seconds // 60
	total_duration_remaining = total_duration_seconds % 60

	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	serialized_players = [_serialize_player(player) for player in players]

	return {
		"id": str(room.id),
		"room_code": room.room_code,
		"host_id": str(room.host_id) if room.host_id else None,
		"status": room.status,
		"created_at": room.created_at,
		"started_at": room.started_at,
		"ended_at": room.ended_at,
		"quiz": {
			"id": str(quiz.id),
			"title": quiz.title,
			"description": quiz.description,
			"question_count": question_count,
			"total_duration_seconds": total_duration_seconds,
			"total_duration_formatted": f"~{total_duration_minutes}m {total_duration_remaining}s" if total_duration_minutes > 0 else f"~{total_duration_remaining}s",
			"created_by": str(quiz.created_by) if quiz.created_by else None,
		},
		"players": serialized_players,
		"player_count": len(serialized_players),
		"settings": {
			"max_players": room.max_players,
			"shuffle_questions": room.shuffle_questions,
			"chat_enabled": room.chat_enabled,
			"current_question_order": room.current_question_order,
		},
	}


async def join_room(room_code: str, payload: dict, current_user: UUID, db: Session) -> dict:
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	# Check if player has been kicked from this room
	is_kicked = db.query(KickedPlayer).filter(
		KickedPlayer.room_id == room.id,
		KickedPlayer.user_id == current_user
	).first()

	if is_kicked:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn đã bị loại khỏi phòng này và không thể tham gia lại")

	if room.status != "WAITING":
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Room is not in WAITING status")

	existing = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id, RoomPlayer.user_id == current_user).first()
	if not existing:
		player_count = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).count()
		if player_count >= room.max_players:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Room is full")

	display_name = payload.get("display_name")
	if not display_name:
		user = db.query(User).filter(User.id == current_user).first()
		display_name = user.username if user else "Player"

	# Determine current_question_order based on game status
	current_question_order = 1 if room.status == "PLAYING" else 0

	if existing:
		existing.display_name = display_name
		db.commit()
		db.refresh(existing)
		await manager.broadcast(
			room.room_code,
			{
				"type": "PLAYER_JOINED",
				"data": {
					**_serialize_room_state(room, db),
					"player": _serialize_player(existing),
				},
			},
		)
		return _serialize_player(existing)

	player = RoomPlayer(
		room_id=room.id,
		user_id=current_user,
		display_name=display_name,
		score=0,
		current_question_order=current_question_order
	)
	db.add(player)
	db.commit()
	db.refresh(player)
	await manager.broadcast(
		room.room_code,
		{
			"type": "PLAYER_JOINED",
			"data": {
				**_serialize_room_state(room, db),
				"player": _serialize_player(player),
			},
		},
	)
	return _serialize_player(player)


async def leave_room(room_code: str, current_user: UUID, db: Session) -> None:
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	if room.host_id == current_user:
		if room.status == "WAITING":
			room_state = _serialize_room_state(room, db)
			await manager.broadcast(
				room_code,
				{
					"type": "ROOM_CLOSED",
					"data": {
						**room_state,
						"reason": "HOST_LEFT",
						"message": "Host đã rời phòng, phòng đã đóng.",
					},
				},
			)
			db.delete(room)
			db.commit()
			return None

		_mark_player_finished_on_leave(room, current_user, db)
		await manager.broadcast(
			room_code,
			{
				"type": "HOST_LEFT",
				"data": {
					"room_code": room_code,
					"host_id": str(room.host_id) if room.host_id else None,
					"message": "Host đã rời phòng nhưng phòng vẫn tiếp tục.",
				},
			},
		)
		await _maybe_auto_finalize_game(room_code, room, db)
		return None

	player = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id, RoomPlayer.user_id == current_user).first()
	if player:
		if room.status != "PLAYING":
			departed_player = _serialize_player(player)
			db.delete(player)
			db.commit()
			remaining_players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
			await manager.broadcast(
				room_code,
				{
					"type": "PLAYER_LEFT",
					"data": {
						"room_code": room_code,
						"player": departed_player,
						"players": [_serialize_player(remaining_player) for remaining_player in remaining_players],
						"player_count": len(remaining_players),
					},
				},
			)
			return None

		_mark_player_finished_on_leave(room, current_user, db)
		await manager.broadcast(
			room_code,
			{
				"type": "PLAYER_LEFT",
				"data": {
					"room_code": room_code,
					"player": _serialize_player(player),
					"players": [_serialize_player(remaining_player) for remaining_player in db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()],
					"player_count": db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).count(),
					"message": "Người chơi đã rời phòng trong lúc đang chơi, điểm đã được giữ lại.",
				},
			},
		)
		await _maybe_auto_finalize_game(room_code, room, db)
	return None


async def kick_player(room_code: str, user_id_to_kick: UUID, current_user: UUID, db: Session) -> dict:
	"""Kick a player from the room. Only host can kick players."""
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	# Only host can kick
	if room.host_id != current_user:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can kick players")

	# Cannot kick self
	if user_id_to_kick == current_user:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot kick yourself")

	# Find the player to kick
	player = db.query(RoomPlayer).filter(
		RoomPlayer.room_id == room.id,
		RoomPlayer.user_id == user_id_to_kick
	).first()

	if not player:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found in room")

	# Record the kick
	kicked_entry = KickedPlayer(
		room_id=room.id,
		user_id=user_id_to_kick,
		kicked_at=datetime.now(timezone.utc)
	)
	db.add(kicked_entry)

	# Remove player from room
	kicked_player_data = _serialize_player(player)
	db.delete(player)
	db.commit()

	# Get remaining players
	remaining_players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()

	# Broadcast the kick event
	await manager.broadcast(
		room_code,
		{
			"type": "PLAYER_KICKED",
			"data": {
				"room_code": room_code,
				"kicked_player": kicked_player_data,
				"kicked_user_id": str(user_id_to_kick),
				"players": [_serialize_player(p) for p in remaining_players],
				"player_count": len(remaining_players),
				"message": f"Người chơi {player.display_name} đã bị loại khỏi phòng bởi host.",
			},
		},
	)

	return {
		"kicked_player": kicked_player_data,
		"remaining_players": [_serialize_player(p) for p in remaining_players],
		"player_count": len(remaining_players),
		"message": f"Đã loại {player.display_name} khỏi phòng",
	}


def get_room_players(room_code: str, db: Session) -> list:
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		return redis_manager.get_room_players(room_code, include_left=False)

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	return [_serialize_player(player) for player in players]


def _get_leaderboard(room: GameRoom, db: Session) -> list:
	"""Helper to get live leaderboard from submitted answers (no interim score persistence)."""
	if redis_manager.room_exists(room.room_code):
		return redis_manager.get_leaderboard(room.room_code)

	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	
	# If no players in RoomPlayer, reconstruct from PlayerAnswer + User
	if not players:
		distinct_user_ids = db.query(PlayerAnswer.user_id).filter(
			PlayerAnswer.room_id == room.id
		).distinct().all()
		
		reconstructed_players = []
		for (user_id,) in distinct_user_ids:
			user = db.query(User).filter(User.id == user_id).first()
			if user:
				class MockPlayer:
					pass
				mock = MockPlayer()
				mock.user_id = user_id
				mock.display_name = user.username
				reconstructed_players.append(mock)
		players = reconstructed_players
	
	score_map = _build_live_score_map(room, db)
	sorted_players = sorted(
		players,
		key=lambda player: (
			-score_map.get(str(player.user_id), 0),
			(player.display_name or "").lower(),
			str(player.user_id),
		),
	)
	return [
		{
			"rank": idx + 1,
			"user_id": str(player.user_id),
			"display_name": player.display_name,
			"score": score_map.get(str(player.user_id), 0),
		}
		for idx, player in enumerate(sorted_players)
	]


def _get_room_results_rows(room: GameRoom, db: Session) -> list:
	if room.status != "FINISHED" and redis_manager.room_exists(room.room_code):
		live_leaderboard = redis_manager.get_leaderboard(room.room_code)
		return [
			{
				"id": None,
				"room_id": str(room.id),
				"user_id": item["user_id"],
				"display_name": item["display_name"],
				"final_score": item["score"],
				"rank": item["rank"],
				"created_at": None,
			}
			for item in live_leaderboard
		]

	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	players_by_user_id = {str(player.user_id): player for player in players}
	game_results = db.query(GameResult).filter(GameResult.room_id == room.id).all()

	if room.status == "FINISHED" and game_results:
		sorted_results = sorted(game_results, key=lambda result: result.rank or 0)
		return [
			{
				"id": str(result.id),
				"room_id": str(result.room_id),
				"user_id": str(result.user_id),
				"display_name": players_by_user_id.get(str(result.user_id)).display_name if players_by_user_id.get(str(result.user_id)) else None,
				"final_score": result.final_score,
				"rank": result.rank,
				"created_at": result.created_at,
			}
			for result in sorted_results
		]

	live_leaderboard = _get_leaderboard(room, db)
	return [
		{
			"id": None,
			"room_id": str(room.id),
			"user_id": item["user_id"],
			"display_name": item["display_name"],
			"final_score": item["score"],
			"rank": item["rank"],
			"created_at": None,
		}
		for item in live_leaderboard
	]


def _all_players_finished(room: GameRoom, db: Session) -> bool:
	if redis_manager.room_exists(room.room_code):
		return redis_manager.active_player_count(room.room_code) == 0

	total_questions = db.query(GameQuestion).filter(GameQuestion.room_id == room.id).count()
	if total_questions == 0:
		return False

	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	if not players:
		return True

	for player in players:
		if (player.current_question_order or 0) <= total_questions:
			return False

	return True


def _mark_player_finished_on_leave(room: GameRoom, user_id: UUID, db: Session) -> bool:
	if room.status != "PLAYING":
		return False

	if redis_manager.room_exists(room.room_code):
		redis_manager.set_player_left(room.room_code, str(user_id))

	player = db.query(RoomPlayer).filter(
		RoomPlayer.room_id == room.id,
		RoomPlayer.user_id == user_id,
	).first()
	if not player:
		return False

	db.delete(player)
	db.commit()
	return True


def _finalize_game_results(room: GameRoom, db: Session) -> list:
	"""Persist final results and user stats exactly once per room."""
	if redis_manager.room_exists(room.room_code):
		meta = redis_manager.get_room_meta(room.room_code) or {}
		if room.status != "FINISHED":
			room.status = "FINISHED"
			room.ended_at = datetime.now(timezone.utc)

		players = redis_manager.get_room_players(room.room_code, include_left=False)
		players_by_user_id = {str(player.get("user_id")): player for player in players if player.get("status") != "LEFT"}
		final_leaderboard = redis_manager.get_leaderboard(room.room_code)
		existing_results = {
			str(result.user_id): result
			for result in db.query(GameResult).filter(GameResult.room_id == room.id).all()
		}
		columns = {column["name"] for column in inspect(db.bind).get_columns("user_stats")}
		has_wins_column = "wins" in columns

		existing_answers = {
			f"{str(answer.user_id)}:{str(answer.question_id)}"
			for answer in db.query(PlayerAnswer).filter(PlayerAnswer.room_id == room.id).all()
		}

		for item in final_leaderboard:
			user_id = item["user_id"]
			rank = item["rank"]
			score = item["score"]
			player = players_by_user_id.get(user_id)
			if not player:
				continue

			for answer_payload in redis_manager.get_answers_for_player(room.room_code, user_id):
				answer_key = f"{user_id}:{answer_payload.get('question_id')}"
				if answer_key in existing_answers:
					continue
				db.add(
					PlayerAnswer(
						room_id=room.id,
						user_id=UUID(user_id),
						question_id=UUID(str(answer_payload.get("question_id"))),
						selected_option_id=UUID(str(answer_payload.get("selected_option_id"))) if answer_payload.get("selected_option_id") else None,
						is_correct=bool(answer_payload.get("is_correct")),
						response_time=float(answer_payload.get("response_time") or 0),
					)
				)

			result = existing_results.get(user_id)
			if result:
				result.final_score = score
				result.rank = rank
			else:
				db.add(
					GameResult(
						room_id=room.id,
						user_id=UUID(user_id),
						final_score=score,
						rank=rank,
					)
				)

			_update_user_stats_compat(
				db=db,
				user_id=UUID(user_id),
				score=score,
				is_winner=(rank == 1),
				has_wins_column=has_wins_column,
			)

		db.commit()
		redis_manager.delete_room_session(room.room_code)
		db.refresh(room)
		return _get_room_results_rows(room, db)

	if room.status != "FINISHED":
		room.status = "FINISHED"
		room.ended_at = datetime.now(timezone.utc)

	# Get players from RoomPlayer, but if empty, get from PlayerAnswer
	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	players_by_user_id = {str(player.user_id): player for player in players}
	
	# If no players in RoomPlayer, reconstruct from PlayerAnswer + User
	if not players_by_user_id:
		distinct_user_ids = db.query(PlayerAnswer.user_id).filter(
			PlayerAnswer.room_id == room.id
		).distinct().all()
		
		for (user_id,) in distinct_user_ids:
			user = db.query(User).filter(User.id == user_id).first()
			if user:
				# Create a mock player-like object with necessary fields
				class MockPlayer:
					pass
				mock = MockPlayer()
				mock.user_id = user_id
				mock.display_name = user.username
				players_by_user_id[str(user_id)] = mock
	
	final_leaderboard = _get_leaderboard(room, db)
	existing_results = {
		str(result.user_id): result
		for result in db.query(GameResult).filter(GameResult.room_id == room.id).all()
	}
	columns = {column["name"] for column in inspect(db.bind).get_columns("user_stats")}
	has_wins_column = "wins" in columns

	for item in final_leaderboard:
		user_id = item["user_id"]
		rank = item["rank"]
		score = item["score"]
		player = players_by_user_id.get(user_id)
		if not player:
			continue

		result = existing_results.get(user_id)
		if result:
			result.final_score = score
			result.rank = rank
		else:
			db.add(
				GameResult(
					room_id=room.id,
					user_id=UUID(user_id),
					final_score=score,
					rank=rank,
				)
			)

		_update_user_stats_compat(
			db=db,
			user_id=UUID(user_id),
			score=score,
			is_winner=(rank == 1),
			has_wins_column=has_wins_column,
		)

	db.commit()
	db.refresh(room)
	return _get_room_results_rows(room, db)


async def _maybe_auto_finalize_game(room_code: str, room: GameRoom, db: Session) -> list | None:
	if room.status == "FINISHED":
		return None

	if not _all_players_finished(room, db):
		return None

	final_rows = _finalize_game_results(room, db)
	await manager.broadcast(
		room_code,
		{
			"type": "GAME_ENDED",
			"data": {
				"room_code": room_code,
				"final_leaderboard": _get_leaderboard(room, db),
				"ended_at": room.ended_at.isoformat() if room.ended_at else None,
			},
		},
	)
	return final_rows


async def start_game(room_code: str, current_user: UUID, db: Session) -> dict:
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	if room.host_id != current_user:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can start the game")

	# Create game_questions from quiz questions
	quiz = room.quiz
	quiz_questions = sorted(
		list(quiz.questions or []),
		key=lambda q: q.order_index or 0
	)
	
	if not quiz_questions:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quiz has no questions")

	# Shuffle if enabled
	if room.shuffle_questions:
		import random
		shuffled = quiz_questions.copy()
		random.shuffle(shuffled)
		quiz_questions = shuffled

	# Create GameQuestion records
	for order_idx, question in enumerate(quiz_questions, start=1):
		game_question = GameQuestion(
			room_id=room.id,
			question_id=question.id,
			question_order=order_idx
		)
		db.add(game_question)

	room.status = "PLAYING"
	room.started_at = datetime.now(timezone.utc)
	room.current_question_order = 1  # Start at first question (for reference only)
	
	# Initialize each player's question progress
	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	for player in players:
		player.current_question_order = 1
	
	db.commit()
	db.refresh(room)

	# Broadcast GAME_STARTED
	players = db.query(RoomPlayer).filter(RoomPlayer.room_id == room.id).all()
	quiz_payload = _quiz_payload_from_quiz(quiz)
	room_payload = _room_payload_from_room(room)
	cache_questions = [
		_serialize_question_for_cache(question, order_idx)
		for order_idx, question in enumerate(quiz_questions, start=1)
	]
	cache_players = [_player_payload_from_room_player(player) for player in players]
	redis_manager.initialize_game_session(room_payload, quiz_payload, cache_players, cache_questions)

	await manager.broadcast(
		room_code,
		{
			"type": "GAME_STARTED",
			"data": _serialize_room_state(room, db),
		},
	)

	# Broadcast initial QUESTION_CHANGED
	if cache_questions:
		await manager.broadcast(
			room_code,
			{
				"type": "QUESTION_CHANGED",
				"data": {
					"current_question_order": 1,
					"total_questions": len(quiz_questions),
					"question": _question_from_cache(cache_questions[0]),
				},
			},
		)

	return _serialize_room(room)


def get_room_results(room_code: str, db: Session) -> list:
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	return _get_room_results_rows(room, db)


def get_room_chat(room_code: str, db: Session, limit: int = 50, offset: int = 0) -> list:
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	messages = (
		db.query(ChatMessage)
		.filter(ChatMessage.room_id == room.id)
		.order_by(ChatMessage.created_at.desc())
		.offset(offset)
		.limit(limit)
		.all()
	)
	messages.reverse()
	return [_serialize_chat_message(message) for message in messages]


async def post_chat_message(room_code: str, current_user: UUID, payload: dict, db: Session) -> dict:
	"""Post a chat message to room"""
	# Always query database first to get authoritative room data
	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	if not room.chat_enabled:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chat is disabled in this room")

	# Verify user is in room (check database first, then Redis cache for status)
	player_db = db.query(RoomPlayer).filter(
		RoomPlayer.room_id == room.id,
		RoomPlayer.user_id == current_user
	).first()
	
	if not player_db:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not in this room")

	# Check Redis for player status (optional, for real-time validation)
	player_redis = redis_manager.get_player(room_code, str(current_user))
	if player_redis and player_redis.get("status") == "LEFT":
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You have left this room")

	# Validate message
	message_text = payload.get("message", "").strip()
	if not message_text:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

	if len(message_text) > 500:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message is too long")

	# Create message using database room ID
	message = ChatMessage(
		room_id=room.id,  # Use authoritative database room ID
		user_id=current_user,
		message=message_text
	)
	db.add(message)
	db.commit()
	db.refresh(message)

	# Build response with player info
	player_display_name = player_redis.get("display_name") if player_redis else player_db.display_name if hasattr(player_db, 'display_name') else "Unknown"
	
	chat_payload = {
		"id": str(message.id),
		"room_id": str(message.room_id),
		"user_id": str(message.user_id),
		"message": message.message,
		"created_at": message.created_at,
		"updated_at": message.updated_at,
		"user": {
			"id": str(current_user),
			"username": player_display_name,
		},
	}
	
	# Broadcast to all connected players
	await manager.broadcast(
		room_code,
		{
			"type": "CHAT_MESSAGE",
			"data": chat_payload,
		},
	)

	return chat_payload


async def submit_answer(room_code: str, current_user: UUID, payload: dict, db: Session) -> dict:
	"""Submit answer to current question"""
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		if cached_meta.get("status") != "PLAYING":
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Game is not playing")

		player = redis_manager.get_player(room_code, str(current_user))
		if not player or player.get("status") == "LEFT":
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not in this room")

		current_question_order = int(player.get("current_question_order") or 1)
		game_question = redis_manager.get_question(room_code, current_question_order)
		if not game_question:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Current question not found")

		question_id = str(game_question.get("id"))
		if redis_manager.has_answer(room_code, str(current_user), question_id):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already answered this question")

		selected_option_id = payload.get("selected_option_id")
		selected_option = None
		for option in game_question.get("answer_options", []):
			if str(option.get("id")) == str(selected_option_id):
				selected_option = option
				break
		if not selected_option:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid option")

		correct_option_id = str(game_question.get("correct_option_id") or "")
		is_correct = str(selected_option_id) == correct_option_id
		response_time = float(payload.get("response_time", 0) or 0)
		question_points = int(game_question.get("points") or 0)
		question_time_limit = float(game_question.get("time_limit") or 0)

		points = _calculate_points(is_correct, response_time, question_points, question_time_limit)

		redis_manager.store_answer(
			room_code,
			str(current_user),
			question_id,
			{
				"room_id": cached_meta.get("id"),
				"user_id": str(current_user),
				"question_id": question_id,
				"question_order": current_question_order,
				"selected_option_id": str(selected_option_id),
				"is_correct": is_correct,
				"response_time": response_time,
				"points_earned": points,
			},
		)
		redis_manager.increment_score(room_code, str(current_user), points)
		current_total_score = redis_manager.get_score(room_code, str(current_user))
		leaderboard = redis_manager.get_leaderboard(room_code)

		await manager.broadcast(
			room_code,
			{
				"type": "PLAYER_ANSWERED",
				"data": {
					"user_id": str(current_user),
					"question_order": current_question_order,
					"is_correct": is_correct,
					"correct_option_id": correct_option_id or None,
					"points_earned": points,
					"leaderboard": leaderboard,
				},
			},
		)

		return {
			"question_order": current_question_order,
			"is_correct": is_correct,
			"correct_option_id": correct_option_id or None,
			"points_earned": points,
			"total_score": current_total_score,
			"leaderboard": leaderboard,
		}

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	if room.status != "PLAYING":
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Game is not playing")

	# Get player
	player = db.query(RoomPlayer).filter(
		RoomPlayer.room_id == room.id,
		RoomPlayer.user_id == current_user
	).first()
	if not player:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not in this room")

	# Get current question
	current_question_order = player.current_question_order or 1
	game_question = db.query(GameQuestion).filter(
		GameQuestion.room_id == room.id,
		GameQuestion.question_order == current_question_order
	).first()
	if not game_question:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Current question not found")

	# Check if already answered
	existing_answer = db.query(PlayerAnswer).filter(
		PlayerAnswer.room_id == room.id,
		PlayerAnswer.user_id == current_user,
		PlayerAnswer.question_id == game_question.question_id
	).first()
	if existing_answer:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already answered this question")

	# Get selected option
	selected_option_id = payload.get("selected_option_id")
	selected_option = db.query(AnswerOption).filter(AnswerOption.id == selected_option_id).first()
	if not selected_option:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid option")

	if selected_option.question_id != game_question.question_id:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected option does not belong to current question")

	correct_option = db.query(AnswerOption).filter(
		AnswerOption.question_id == game_question.question_id,
		AnswerOption.is_correct == True
	).first()

	question = game_question.question
	is_correct = selected_option.is_correct
	response_time = float(payload.get("response_time", 0) or 0)

	# Calculate score
	points = _calculate_points(is_correct, response_time, question.points, question.time_limit)

	# Create PlayerAnswer
	answer = PlayerAnswer(
		room_id=room.id,
		user_id=current_user,
		question_id=game_question.question_id,
		selected_option_id=selected_option_id,
		is_correct=is_correct,
		response_time=response_time
	)
	db.add(answer)

	db.commit()

	leaderboard = _get_leaderboard(room, db)
	current_total_score = 0
	for item in leaderboard:
		if item["user_id"] == str(current_user):
			current_total_score = item["score"]
			break

	# Broadcast PLAYER_ANSWERED with updated leaderboard
	await manager.broadcast(
		room_code,
		{
			"type": "PLAYER_ANSWERED",
			"data": {
				"user_id": str(current_user),
				"question_order": current_question_order,
				"is_correct": is_correct,
				"correct_option_id": str(correct_option.id) if correct_option else None,
				"points_earned": points,
				"leaderboard": leaderboard,
			},
		},
	)

	return {
		"question_order": current_question_order,
		"is_correct": is_correct,
		"correct_option_id": str(correct_option.id) if correct_option else None,
		"points_earned": points,
		"total_score": current_total_score,
		"leaderboard": leaderboard,
	}


async def next_question(room_code: str, current_user: UUID, db: Session) -> dict:
	"""Move to next question - each player advances independently"""
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		if cached_meta.get("status") == "FINISHED":
			player = redis_manager.get_player(room_code, str(current_user))
			total_questions = redis_manager.get_total_questions(room_code)
			return {
				"status": "FINISHED",
				"current_question_order": player.get("current_question_order") if player else total_questions,
				"total_questions": total_questions,
			}

		if cached_meta.get("status") != "PLAYING":
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Game is not playing")

		player = redis_manager.get_player(room_code, str(current_user))
		if not player or player.get("status") == "LEFT":
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not in room")

		total_questions = redis_manager.get_total_questions(room_code)
		current_order = int(player.get("current_question_order") or 1)

		if current_order >= total_questions:
			redis_manager.set_player_finished(room_code, str(current_user))
			if redis_manager.active_player_count(room_code) == 0 and cached_meta.get("status") != "FINISHED":
				room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
				if room:
					_finalize_game_results(room, db)
			return {
				"status": "FINISHED",
				"current_question_order": current_order,
				"total_questions": total_questions,
			}

		next_order = current_order + 1
		redis_manager.set_player_current_question_order(room_code, str(current_user), next_order)
		game_question = redis_manager.get_question(room_code, next_order)
		return {
			"current_question_order": next_order,
			"total_questions": total_questions,
			"question": _question_from_cache(game_question),
			"status": "OK",
		}

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	if room.status == "FINISHED":
		player = db.query(RoomPlayer).filter(
			RoomPlayer.room_id == room.id,
			RoomPlayer.user_id == current_user
		).first()
		total_questions = db.query(GameQuestion).filter(GameQuestion.room_id == room.id).count()
		return {
			"status": "FINISHED",
			"current_question_order": player.current_question_order if player else total_questions,
			"total_questions": total_questions,
		}

	if room.status != "PLAYING":
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Game is not playing")

	# Get current player in room
	player = db.query(RoomPlayer).filter(
		RoomPlayer.room_id == room.id,
		RoomPlayer.user_id == current_user
	).first()
	
	if not player:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not in room")

	# Get total questions
	total_questions = db.query(GameQuestion).filter(GameQuestion.room_id == room.id).count()
	current_order = player.current_question_order

	if current_order >= total_questions:
		player.current_question_order = total_questions + 1
		db.commit()
		db.refresh(player)

		if room.status != "FINISHED":
			await _maybe_auto_finalize_game(room_code, room, db)

		# Player finished all questions
		return {
			"status": "FINISHED",
			"current_question_order": current_order,
			"total_questions": total_questions,
		}

	# Move to next question for this player only
	next_order = current_order + 1
	player.current_question_order = next_order
	db.commit()
	db.refresh(player)

	# Get next question
	game_question = db.query(GameQuestion).filter(
		GameQuestion.room_id == room.id,
		GameQuestion.question_order == next_order
	).first()

	return {
		"current_question_order": next_order,
		"total_questions": total_questions,
		"question": _serialize_question(game_question.question) if game_question else None,
		"status": "OK",
	}


async def finish_game(room_code: str, current_user: UUID, db: Session) -> dict:
	"""Finish game and create results"""
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
		if not room:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

		if room.host_id != current_user:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can finish game")

		results_exist = db.query(GameResult).filter(GameResult.room_id == room.id).first() is not None
		if room.status != "FINISHED" or not results_exist:
			_finalize_game_results(room, db)
			await manager.broadcast(
				room_code,
				{
					"type": "GAME_ENDED",
					"data": {
						"room_code": room_code,
						"final_leaderboard": _get_leaderboard(room, db),
						"ended_at": room.ended_at.isoformat() if room.ended_at else None,
					},
				},
			)

		return {
			"status": "FINISHED",
			"final_leaderboard": _get_leaderboard(room, db),
			"results": _get_room_results_rows(room, db),
		}

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	if room.host_id != current_user:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only host can finish game")

	results_exist = db.query(GameResult).filter(GameResult.room_id == room.id).first() is not None
	if room.status != "FINISHED" or not results_exist:
		_finalize_game_results(room, db)
		await manager.broadcast(
			room_code,
			{
				"type": "GAME_ENDED",
				"data": {
					"room_code": room_code,
					"final_leaderboard": _get_leaderboard(room, db),
					"ended_at": room.ended_at.isoformat() if room.ended_at else None,
				},
			},
		)

	return {
		"status": "FINISHED",
		"final_leaderboard": _get_leaderboard(room, db),
		"results": _get_room_results_rows(room, db),
	}


def get_room_leaderboard(room_code: str, db: Session) -> dict:
	"""Get current room leaderboard"""
	cached_meta = redis_manager.get_room_meta(room_code)
	if cached_meta:
		return {
			"room_code": room_code,
			"status": cached_meta.get("status"),
			"leaderboard": redis_manager.get_leaderboard(room_code),
		}

	room = db.query(GameRoom).filter(GameRoom.room_code == room_code).first()
	if not room:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

	return {
		"room_code": room_code,
		"status": room.status,
		"leaderboard": _get_leaderboard(room, db),
	}
