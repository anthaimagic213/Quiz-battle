from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from uuid import uuid4
from app.db.base_class import BaseModel


class User(BaseModel):
    """
    User authentication & identity - domain: USERS & AUTH
    Core identity and credentials for system authentication
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    username = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255))
    email = Column(String(255), unique=True, nullable=False, index=True)
    avatar_url = Column(Text)
    password_hash = Column(Text, nullable=False)

    # Auth domain relationships
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

    # Quiz content relationships
    quizzes = relationship("Quiz", back_populates="creator", cascade="all, delete-orphan")

    # Game play relationships
    game_rooms = relationship("GameRoom", back_populates="host", cascade="all, delete-orphan")
    room_players = relationship("RoomPlayer", back_populates="user", cascade="all, delete-orphan")
    player_answers = relationship("PlayerAnswer", back_populates="user", cascade="all, delete-orphan")
    game_results = relationship("GameResult", back_populates="user", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")
    kicked_players = relationship("KickedPlayer", back_populates="user", cascade="all, delete-orphan")

    # User stats relationship
    user_stats = relationship("UserStats", back_populates="user", uselist=False, cascade="all, delete-orphan")

    # Social relationships
    friend_requests_sent = relationship("FriendRequest", foreign_keys="FriendRequest.requester_id", back_populates="requester", cascade="all, delete-orphan")
    friend_requests_received = relationship("FriendRequest", foreign_keys="FriendRequest.addressee_id", back_populates="addressee", cascade="all, delete-orphan")
    friendships_1 = relationship("Friendship", foreign_keys="Friendship.user_id_1", back_populates="user_1", cascade="all, delete-orphan")
    friendships_2 = relationship("Friendship", foreign_keys="Friendship.user_id_2", back_populates="user_2", cascade="all, delete-orphan")
    conversation_members = relationship("ConversationMember", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="sender", cascade="all, delete-orphan")
