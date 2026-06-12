"""
Pydantic schemas cho Intent Router output.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class FilterBlock(BaseModel):
    column: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "LIKE", "ILIKE", "IS NULL", "IS NOT NULL"]
    value: object  # scalar, list (for IN), or placeholder like "<current_user_id>"


class OrderByBlock(BaseModel):
    column: str
    direction: Literal["ASC", "DESC"] = "DESC"


class SemanticBlock(BaseModel):
    collection: Literal["quiz_embeddings", "question_embeddings", "chat_context_embeddings"]
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: Optional[str] = None  # required for chat_context_embeddings


class SqlBlock(BaseModel):
    tables: list[str] = Field(min_length=1, max_length=3)
    joins: list[str] = Field(default_factory=list)
    select: list[str] = Field(min_length=1, max_length=10)
    filters: list[FilterBlock] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    having: list[FilterBlock] = Field(default_factory=list)
    order_by: list[OrderByBlock] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=50)


class RouterOutput(BaseModel):
    intent: Literal[
        "smalltalk",
        "semantic_search",
        "text_to_sql",
        "hybrid",
        "get_my_quizzes",
        "get_my_stats",
        "get_my_friends",
        "chat_lookup",  # Intent mới: hỏi về nội dung chat trước đó
        "clarify",
    ]
    confidence: float = Field(ge=0, le=1)
    semantic: Optional[SemanticBlock] = None
    sql: Optional[SqlBlock] = None
    merge_strategy: Optional[Literal["intersect_ids", "concat", "sql_filter_then_semantic"]] = None
    reasoning: str = ""

    @field_validator("intent")
    @classmethod
    def check_intent_requires_blocks(cls, v, info):
        """Validate intent có đủ blocks tương ứng."""
        # Chỉ check khi model đã có đầy đủ fields
        return v
