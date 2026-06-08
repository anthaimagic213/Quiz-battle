from typing import Dict, Set
from fastapi import WebSocket

from app.services.redis_pubsub import publish_ws_event


class ConnectionManager:
	def __init__(self) -> None:
		self.active_connections: Dict[str, Set[WebSocket]] = {}
		self.connection_users: Dict[WebSocket, str] = {}
		self.room_user_connections: Dict[str, Dict[str, Set[WebSocket]]] = {}

	async def connect(self, room_code: str, user_id: str, websocket: WebSocket) -> None:
		await websocket.accept()
		self.active_connections.setdefault(room_code, set()).add(websocket)
		self.connection_users[websocket] = user_id
		self.room_user_connections.setdefault(room_code, {}).setdefault(user_id, set()).add(websocket)

	def disconnect(self, room_code: str, user_id: str, websocket: WebSocket) -> None:
		connections = self.active_connections.get(room_code)
		if connections:
			connections.discard(websocket)
			if not connections:
				self.active_connections.pop(room_code, None)

		self.connection_users.pop(websocket, None)

		room_users = self.room_user_connections.get(room_code)
		if not room_users:
			return

		user_connections = room_users.get(user_id)
		if user_connections:
			user_connections.discard(websocket)
			if not user_connections:
				room_users.pop(user_id, None)

		if not room_users:
			self.room_user_connections.pop(room_code, None)

	def has_user_connection(self, room_code: str, user_id: str) -> bool:
		room_users = self.room_user_connections.get(room_code)
		if not room_users:
			return False
		return bool(room_users.get(user_id))

	async def broadcast_local(self, room_code: str, message: dict) -> None:
		connections = self.active_connections.get(room_code, set())
		stale: Set[WebSocket] = set()

		for connection in list(connections):
			try:
				await connection.send_json(message)
			except Exception:
				stale.add(connection)

		if not stale:
			return

		room_users = self.room_user_connections.get(room_code, {})
		for websocket in stale:
			user_id = self.connection_users.get(websocket)
			if user_id:
				user_sockets = room_users.get(user_id)
				if user_sockets:
					user_sockets.discard(websocket)
					if not user_sockets:
						room_users.pop(user_id, None)
			self.connection_users.pop(websocket, None)
			connections.discard(websocket)

		if not connections:
			self.active_connections.pop(room_code, None)
		if room_users == {}:
			self.room_user_connections.pop(room_code, None)

	async def broadcast(self, room_code: str, message: dict) -> None:
		"""Broadcast locally and publish to Redis so other instances relay."""
		await self.broadcast_local(room_code, message)
		await publish_ws_event(room_code, message)


# Shared singleton instance used by both game_socket and chat_socket
manager = ConnectionManager()
