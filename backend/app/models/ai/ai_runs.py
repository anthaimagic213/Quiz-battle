"""
ai_runs table - Audit log cho mọi AI reply.

Theo PHASE3_SETUP.md mục 6:
- 1 row / 1 AI reply
- Lưu router output, tool calls, prompt, token usage, latency
- Mục đích: debug, cost tracking, eval dataset
- KHÔNG hiển thị cho user
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    DateTime,
    String,
    Text,
    Integer,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from uuid import uuid4
from datetime import datetime

from app.db.base_class import BaseModel


class AIRun(BaseModel):
    __tablename__ = "ai_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign keys
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ai_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Routing
    intent = Column(String(50), nullable=False)
    router_raw = Column(JSONB, nullable=True)
    router_retries = Column(Integer, default=0, nullable=False)

    # Tool execution
    tool_calls = Column(JSONB, nullable=True)

    # Prompt snapshot
    composer_system = Column(Text, nullable=True)
    composer_user = Column(Text, nullable=True)
    composer_raw = Column(Text, nullable=True)

    # Token usage
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)

    # Model
    model_name = Column(String(100), nullable=True)

    # Latency (ms)
    router_ms = Column(Integer, nullable=True)
    tool_ms = Column(Integer, nullable=True)
    composer_ms = Column(Integer, nullable=True)
    total_ms = Column(Integer, nullable=True)

    # Error tracking
    error = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AIRun id={self.id} intent={self.intent} "
            f"conv={self.conversation_id} total_ms={self.total_ms}>"
        )
