"""
AI Orchestrator - Glue giữa router, tools, composer, persist.

End-to-end flow (theo PHASE3_SETUP.md mục 7):

    User message
        ↓
    1. Intent Router (LLM call #1)
        ↓
    2. Validate RouterOutput
        ↓
    3. Build/get tool args (inject current_user_id cho get_my_*)
        ↓
    4. Run tool(s) (semantic_search / safe_sql / hybrid)
        ↓
    5. Composer (LLM call #2) — format tool_results → answer
        ↓
    6. Persist AI message (sender_type="ai")
        ↓
    7. Write ai_runs audit row
        ↓
    8. Return answer + metadata (cho WebSocket broadcast)

Đặc biệt:
- "nếu LLM không phân loại được thì cứ auto Qdrant mà tìm trước" → router fallback semantic_search
- Mọi step có try/except + logging, không bao giờ raise ra ngoài (trừ input invalid)
- Persist lỗi chỉ log warning, vẫn return answer để UX không bị block
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.ai import (
    RouterOutput,
    SqlBlock,
    FilterBlock,
    OrderByBlock,
    SemanticBlock,
)
from app.services.intent_router import classify_intent
from app.services import search_service
from app.services.sql_query_tool import (
    tool_safe_sql_query,
    tool_hybrid_search,
)
from app.services.llm_service import chat_completion, LLMError, CircuitBreakerOpen
from app.services.llm_error_handler import CircuitBreakerOpen as CBOpen
from app.services.message_service import MessageService
from app.services.conversation_service import ConversationService
from app.schemas.social import MessageCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OrchestratorError(Exception):
    """Raised khi input invalid hoặc không thể xử lý."""
    pass


# ---------------------------------------------------------------------------
# Composers (LLM call #2)
# ---------------------------------------------------------------------------


COMPOSER_SYSTEM_PROMPT = """Bạn là trợ lý AI của Quiz Battle — một ứng dụng quiz Việt Nam.

Nhiệm vụ: trả lời câu hỏi của user dựa trên:
1. Recent chat history (nếu có)
2. Tool results (dữ liệu có cấu trúc / semantic search)
3. Chat context RAG (top-5 tin nhắn liên quan trong conversation này, đã được embed & search)
4. KHÔNG bịa thêm data ngoài context.

Quy tắc:
- Trả lời bằng tiếng Việt (hoặc ngôn ngữ user dùng).
- Ngắn gọn, dùng bullet/list nếu nhiều kết quả.
- Luôn cite nguồn: "Theo semantic search..." hoặc "Theo database có N quiz..." hoặc "Theo lịch sử chat...".
- KHI CÓ CHAT CONTEXT (tin nhắn trước đó trong conversation): trả lời dựa trên nội dung tin nhắn thật.
  - Ví dụ: user hỏi "anh Long định chơi quiz gì?" → tìm trong chat context các tin nhắn nói về "anh Long" / "quiz" → trả lời cụ thể.
  - Trích dẫn tên người gửi (sender) và thời gian nếu có trong context.
- Nếu tool trả 0 kết quả VÀ chat context rỗng: nói rõ "Hiện không có thông tin phù hợp".
- KHÔNG tự ý thêm thông tin không có trong context.
- Câu hỏi ngoài phạm vi (vd: "thời tiết hôm nay", "hack hệ thống"): lịch sự từ chối.
- Tối đa 200 từ, ưu tiên thông tin quan trọng nhất.
"""


def _build_composer_messages(
    user_query: str,
    intent: str,
    tool_results: list[dict],
    recent_history: list[dict],
    chat_context_rag: list[dict] | None = None,
) -> list[dict]:
    """Build messages list cho composer call."""
    messages = [{"role": "system", "content": COMPOSER_SYSTEM_PROMPT}]

    # Add recent history (max 3 turns) để có ngữ cảnh hội thoại
    if recent_history:
        for msg in recent_history[-3:]:
            role = "user" if msg.get("sender_type") == "user" else "assistant"
            content = msg.get("content", "")
            if content:
                messages.append({"role": role, "content": content})

    # Add user message + tool context
    tool_summary = json.dumps(tool_results, ensure_ascii=False, indent=2, default=str)

    # Build chat context RAG block (top-5 tin nhắn liên quan từ Qdrant)
    rag_block = ""
    if chat_context_rag:
        rag_lines = []
        for i, hit in enumerate(chat_context_rag, 1):
            payload = hit.get("payload") or {}
            sender = payload.get("sender_id", "unknown")
            sender_type = payload.get("sender_type", "user")
            content = payload.get("content", "")
            created_at = payload.get("created_at", "")
            score = hit.get("score", 0.0)
            rag_lines.append(
                f"[{i}] (score={score:.3f}, sender={sender}, type={sender_type}, at={created_at})\n{content}"
            )
        rag_block = (
            "\n\nChat context (top-{} tin nhắn liên quan trong conversation này "
            "— đã được embed & tìm bằng Qdrant chat_context_embeddings):\n{}".format(
                len(chat_context_rag), "\n\n".join(rag_lines)
            )
        )

    user_content = (
        f"User: {user_query}\n\n"
        f"Intent: {intent}\n\n"
        f"Tool results:\n{tool_summary}"
        f"{rag_block}\n\n"
        f"Hãy soạn câu trả lời tự nhiên, ngắn gọn, dựa trên tool results và chat context (nếu có)."
    )
    messages.append({"role": "user", "content": user_content})

    return messages


def _compose_answer(
    user_query: str,
    intent: str,
    tool_results: list[dict],
    recent_history: list[dict],
    chat_context_rag: list[dict] | None = None,
) -> dict:
    """
    Gọi LLM composer để format tool_results → answer text.

    Args:
        chat_context_rag: top-K hits từ Qdrant chat_context_embeddings
                          (đã được truy vấn ở bước RAG trước).

    Returns:
        {
            "answer": str,
            "usage": dict,
            "error": str | None,
            "truncated": bool,   # True nếu LLM chạm max_tokens
        }
    """
    try:
        messages = _build_composer_messages(
            user_query, intent, tool_results, recent_history,
            chat_context_rag=chat_context_rag,
        )
        # Tính max_tokens động dựa trên payload size (tránh trả lời bị
        # cắt ngang như: "Dựa trên lịch sử chat, ... **2026-0").
        # Heuristic: khi intent là "summarize" hoặc chat_context_rag dài
        # → cần nhiều token hơn để liệt kê tin nhắn.
        dynamic_max = _dynamic_max_tokens(
            intent=intent,
            tool_results=tool_results,
            chat_context_rag=chat_context_rag or [],
        )
        response = chat_completion(
            messages=messages,
            model=settings.LLM_MODEL,
            temperature=0.4,  # cho phép variation trong câu trả lời
            max_tokens=dynamic_max,
        )

        # Detect truncation: nếu completion_tokens chạm max_tokens
        # thì answer có thể bị cắt. Flag để frontend biết.
        completion_tokens = int(
            (response.get("usage") or {}).get("completion_tokens", 0) or 0
        )
        truncated = completion_tokens >= dynamic_max - 5  # trừ buffer

        if truncated:
            logger.warning(
                f"Composer answer truncated: completion_tokens={completion_tokens}, "
                f"max_tokens={dynamic_max}, "
                f"answer_len={len(response['answer'])}"
            )

        return {
            "answer": response["answer"],
            "usage": response["usage"],
            "error": None,
            "truncated": truncated,
            "max_tokens_used": dynamic_max,
        }
    except LLMError as e:
        logger.exception("Composer LLM failed: %s", e)
        return {
            "answer": "Xin lỗi, hiện tại tôi không thể trả lời. Bạn thử lại sau nhé.",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": f"composer_failed: {e}",
            "truncated": False,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("Composer unexpected error: %s", e)
        return {
            "answer": "Đã có lỗi khi tạo câu trả lời. Bạn thử lại sau nhé.",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": f"composer_unexpected: {e}",
            "truncated": False,
        }


def _dynamic_max_tokens(
    intent: str,
    tool_results: list[dict],
    chat_context_rag: list[dict],
) -> int:
    """
    Tính max_tokens động dựa trên độ lớn payload.

    Logic:
    - Baseline: 600 tokens (cho câu trả lời ngắn)
    - Cộng thêm ~60 tokens mỗi hit chat_context (để liệt kê đầy đủ)
    - Cộng thêm ~30 tokens mỗi row tool_result
    - Trần: 3000 tokens (Gemini 2.5 Flash hỗ trợ output đủ lớn)
    - Sàn: 400 tokens
    """
    base = 600
    per_chat_hit = 60
    per_tool_row = 30
    # Gemini 2.5 Flash hỗ trợ output 8K tokens. Set hard_cap = 6000
    # để an toàn (trừ buffer cho safety filters).
    # Nếu dùng Gemini 2.5 Pro / 2.0 Flash Thinking → có thể tăng lên 16000.
    hard_cap = int(getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 6000) or 6000)
    floor = 400

    extra = 0
    extra += per_chat_hit * len(chat_context_rag)
    for tr in tool_results:
        rows = ((tr or {}).get("data") or {}).get("rows") or []
        extra += per_tool_row * min(len(rows), 20)  # cap per-tool

    # Tăng thêm khi intent nghi ngờ là summarize
    summarize_keywords = ("tóm tắt", "summarize", "summary", "recap", "liệt kê", "kể lại")
    user_intent_hint = " ".join([intent or "", " ".join(
        (h.get("payload") or {}).get("content", "")[:120] for h in chat_context_rag[:1]
    )]).lower()
    if any(k in user_intent_hint for k in summarize_keywords):
        extra += 400

    return max(floor, min(base + extra, hard_cap))


# ---------------------------------------------------------------------------
# Tool dispatch (map intent → tool execution)
# ---------------------------------------------------------------------------


def _build_get_my_quizzes_sql(user_id: UUID) -> SqlBlock:
    """Build SQL cho intent=get_my_quizzes."""
    return SqlBlock(
        tables=["quizzes"],
        joins=[],
        select=["id", "title", "description", "created_at"],
        filters=[
            FilterBlock(column="created_by", op="=", value="<current_user_id>"),
            FilterBlock(column="is_deleted", op="=", value=False),
        ],
        order_by=[OrderByBlock(column="created_at", direction="DESC")],
        limit=20,
    )


def _build_get_my_stats_sql(user_id: UUID) -> SqlBlock:
    """Build SQL cho intent=get_my_stats."""
    return SqlBlock(
        tables=["user_stats"],
        joins=[],
        select=["total_games", "total_score", "avg_score", "wins", "updated_at"],
        filters=[
            FilterBlock(column="user_id", op="=", value="<current_user_id>"),
        ],
        limit=1,
    )


def _build_get_my_friends_sql(user_id: UUID) -> SqlBlock:
    """
    Build SQL cho intent=get_my_friends.
    Lấy union của user_id_1 (khi current user là user_2) và user_id_2 (khi current user là user_1).
    """
    return SqlBlock(
        tables=["friendships"],
        joins=[],
        select=["id", "user_id_1", "user_id_2", "created_at"],
        filters=[
            FilterBlock(
                column="user_id_1",
                op="=",
                value="<current_user_id>",
            ),
        ],
        order_by=[OrderByBlock(column="created_at", direction="DESC")],
        limit=50,
    )


def _run_semantic_search(semantic: SemanticBlock) -> dict:
    """Run Qdrant semantic search."""
    try:
        if semantic.collection == "quiz_embeddings":
            hits = search_service.search_quizzes(semantic.query, top_k=semantic.top_k)
        elif semantic.collection == "question_embeddings":
            hits = search_service.search_questions(semantic.query, top_k=semantic.top_k)
        elif semantic.collection == "chat_context_embeddings":
            if not semantic.conversation_id:
                return {
                    "success": False,
                    "error": "conversation_id required for chat_context_embeddings",
                    "source": "semantic_search",
                }
            hits = search_service.search_messages(
                semantic.query,
                conversation_id=semantic.conversation_id,
                top_k=semantic.top_k,
            )
        else:
            return {
                "success": False,
                "error": f"Unknown collection: {semantic.collection}",
                "source": "semantic_search",
            }

        # Format hits thành rows cho composer
        rows = [
            {
                "id": h.get("id"),
                "score": h.get("score"),
                "title": (h.get("payload") or {}).get("title", ""),
                "description": (h.get("payload") or {}).get("description", ""),
            }
            for h in hits
        ]
        return {
            "success": True,
            "data": {
                "columns": ["id", "title", "description", "score"],
                "rows": rows,
                "count": len(rows),
            },
            "source": "semantic_search",
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("Semantic search failed: %s", e)
        return {
            "success": False,
            "error": f"semantic_search_failed: {str(e)[:200]}",
            "source": "semantic_search",
        }


def _run_sql_block(
    sql: SqlBlock,
    current_user_id: UUID | None,
) -> dict:
    """Run SQL query tool (có retry + fallback)."""
    return tool_safe_sql_query(
        query=sql,
        current_user_id=current_user_id,
        timeout_ms=5000,
    )


def _execute_tools(
    router_output: RouterOutput,
    current_user_id: UUID,
) -> list[dict]:
    """
    Execute tool(s) dựa trên RouterOutput.
    Returns list of tool_result dicts.
    """
    intent = router_output.intent
    tool_results: list[dict] = []

    # === smalltalk: không cần tool ===
    if intent == "smalltalk":
        tool_results.append({
            "tool": "none",
            "intent": "smalltalk",
            "data": {"note": "Không cần truy vấn data"},
        })
        return tool_results

    # === clarify: cũng không cần tool, composer hỏi lại ===
    if intent == "clarify":
        tool_results.append({
            "tool": "none",
            "intent": "clarify",
            "data": {"note": "Cần hỏi lại user để làm rõ ý định"},
        })
        return tool_results

    # === get_my_*: tự build SQL, không cần LLM extract ===
    if intent == "get_my_quizzes":
        sql = _build_get_my_quizzes_sql(current_user_id)
        result = _run_sql_block(sql, current_user_id)
        result["tool"] = "safe_sql_query"
        result["intent"] = intent
        tool_results.append(result)
        return tool_results

    if intent == "get_my_stats":
        sql = _build_get_my_stats_sql(current_user_id)
        result = _run_sql_block(sql, current_user_id)
        result["tool"] = "safe_sql_query"
        result["intent"] = intent
        tool_results.append(result)
        return tool_results

    if intent == "get_my_friends":
        # Lấy cả 2 chiều
        sql1 = SqlBlock(
            tables=["friendships"],
            joins=[],
            select=["user_id_2 AS friend_id", "created_at"],
            filters=[FilterBlock(column="user_id_1", op="=", value="<current_user_id>")],
            order_by=[OrderByBlock(column="created_at", direction="DESC")],
            limit=50,
        )
        sql2 = SqlBlock(
            tables=["friendships"],
            joins=[],
            select=["user_id_1 AS friend_id", "created_at"],
            filters=[FilterBlock(column="user_id_2", op="=", value="<current_user_id>")],
            order_by=[OrderByBlock(column="created_at", direction="DESC")],
            limit=50,
        )
        r1 = _run_sql_block(sql1, current_user_id)
        r2 = _run_sql_block(sql2, current_user_id)
        # Merge results
        merged_rows = []
        if r1.get("success"):
            merged_rows.extend(r1.get("data", {}).get("rows", []))
        if r2.get("success"):
            merged_rows.extend(r2.get("data", {}).get("rows", []))
        # Dedup by friend_id
        seen = set()
        deduped = []
        for row in merged_rows:
            fid = row.get("friend_id")
            if fid and fid not in seen:
                seen.add(fid)
                deduped.append(row)
        tool_results.append({
            "tool": "safe_sql_query",
            "intent": intent,
            "success": True,
            "data": {
                "columns": ["friend_id", "created_at"],
                "rows": deduped,
                "count": len(deduped),
            },
            "source": "sql",
        })
        return tool_results

    # === semantic_search ===
    if intent == "semantic_search":
        if router_output.semantic:
            result = _run_semantic_search(router_output.semantic)
            result["tool"] = "semantic_search"
            result["intent"] = intent
            tool_results.append(result)
        else:
            tool_results.append({
                "tool": "semantic_search",
                "intent": intent,
                "success": False,
                "error": "Missing semantic block (router output invalid)",
            })
        return tool_results
    
    # === chat_lookup: tương tự semantic_search nhưng dùng chat_context_embeddings ===
    if intent == "chat_lookup":
        if router_output.semantic:
            result = _run_semantic_search(router_output.semantic)
            result["tool"] = "chat_lookup"
            result["intent"] = intent
            tool_results.append(result)
        else:
            tool_results.append({
                "tool": "chat_lookup",
                "intent": intent,
                "success": False,
                "error": "Missing semantic block (router output invalid)",
            })
        return tool_results

    # === text_to_sql ===
    if intent == "text_to_sql":
        if router_output.sql:
            result = _run_sql_block(router_output.sql, current_user_id)
            result["tool"] = "safe_sql_query"
            result["intent"] = intent
            tool_results.append(result)
        else:
            tool_results.append({
                "tool": "safe_sql_query",
                "intent": intent,
                "success": False,
                "error": "Missing sql block (router output invalid)",
            })
        return tool_results

    # === hybrid: chạy cả 2 ===
    if intent == "hybrid":
        result = tool_hybrid_search(
            router_output=router_output,
            current_user_id=current_user_id,
        )
        result["tool"] = "hybrid_search"
        result["intent"] = intent
        tool_results.append(result)
        return tool_results

    # Fallback không xác định → chạy semantic search
    logger.warning(f"Unknown intent '{intent}', defaulting to semantic_search")
    if router_output.semantic:
        result = _run_semantic_search(router_output.semantic)
        result["tool"] = "semantic_search"
        result["intent"] = "semantic_search_fallback"
        tool_results.append(result)
    return tool_results


# ---------------------------------------------------------------------------
# ai_runs audit
# ---------------------------------------------------------------------------


def _write_ai_run_audit(
    db: Session,
    conversation_id: UUID,
    user_message_id: UUID,
    ai_message_id: UUID | None,
    router_output: RouterOutput,
    tool_results: list[dict],
    composer_result: dict,
    router_retries: int,
    timings: dict,
    error: str | None,
) -> None:
    """
    Ghi 1 row vào bảng ai_runs (nếu model tồn tại).
    Best-effort: lỗi chỉ log warning, không phá flow.
    """
    try:
        from app.models.ai.ai_runs import AIRun  # type: ignore
    except ImportError:
        logger.debug("ai_runs model not available, skipping audit")
        return

    try:
        # Tổng hợp token usage
        composer_usage = composer_result.get("usage", {})
        prompt_tokens = int(composer_usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(composer_usage.get("completion_tokens", 0) or 0)

        # Tool calls summary
        tool_summary = []
        for tr in tool_results:
            tool_summary.append({
                "tool": tr.get("tool"),
                "intent": tr.get("intent"),
                "success": tr.get("success"),
                "source": tr.get("source"),
                "error": tr.get("error"),
                "data_count": (
                    tr.get("data", {}).get("count")
                    if isinstance(tr.get("data"), dict)
                    else None
                ),
            })

        ai_run = AIRun(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            ai_message_id=ai_message_id,
            intent=router_output.intent,
            router_raw=router_output.model_dump(mode="json"),
            router_retries=router_retries,
            tool_calls=tool_summary,
            composer_raw=composer_result.get("answer", ""),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model_name=settings.LLM_MODEL,
            router_ms=timings.get("router_ms"),
            tool_ms=timings.get("tool_ms"),
            composer_ms=timings.get("composer_ms"),
            total_ms=timings.get("total_ms"),
            error=error,
        )
        db.add(ai_run)
        db.commit()
        logger.info(f"ai_runs audit written: intent={router_output.intent}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to write ai_runs audit: {e}")
        try:
            db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Circuit breaker error handling
# ---------------------------------------------------------------------------


def _handle_circuit_breaker_open(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    user_message_id: UUID,
    timings: dict,
) -> dict:
    """
    Xử lý khi circuit breaker OPEN (LLM proxy không khả dụng).
    Trả về câu trả lời mặc định cho user.
    """
    answer_text = (
        "Xin lỗi, hiện tại trợ lý AI đang tạm thời không khả dụng do quá tải. "
        "Bạn có thể thử lại sau vài phút hoặc liên hệ admin nếu vấn đề kéo dài."
    )
    
    # Persist AI message (best-effort)
    ai_message_id: UUID | None = None
    try:
        ai_msg_data = MessageCreate(
            content=answer_text,
            metadata={
                "intent": "circuit_breaker_open",
                "error": "LLM service unavailable",
            },
        )
        ai_msg = MessageService.create_message(
            db=db,
            conversation_id=conversation_id,
            sender_id=user_id,
            data=ai_msg_data,
        )
        from app.models.social.messages import Message
        db.query(Message).filter(Message.id == ai_msg["id"]).update({
            "sender_type": "ai",
            "is_ai_generated": True,
        })
        db.commit()
        ai_message_id = UUID(ai_msg["id"])
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Failed to persist circuit breaker message: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    
    timings["total_ms"] = sum(timings.values())
    
    return {
        "answer": answer_text,
        "intent": "circuit_breaker_open",
        "confidence": 0.0,
        "tool_results": [],
        "chat_context_rag": [],
        "ai_message_id": ai_message_id,
        "truncated": False,
        "timings": timings,
        "error": "circuit_breaker_open",
        "router_reasoning": "LLM service unavailable",
    }


# ---------------------------------------------------------------------------
# Main orchestrator entry
# ---------------------------------------------------------------------------


def run_ai_orchestrator(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    user_message: str,
    user_message_id: UUID,
    recent_history: list[dict] | None = None,
) -> dict:
    """
    End-to-end AI pipeline.

    Args:
        db: SQLAlchemy session
        conversation_id: UUID conversation hiện tại
        user_id: UUID user gửi message
        user_message: nội dung message
        user_message_id: UUID message vừa persist
        recent_history: list[{sender_type, content}] các message gần nhất

    Returns:
        {
            "answer": str,                    # câu trả lời cho user
            "intent": str,                    # intent đã phân loại
            "confidence": float,
            "tool_results": [...],
            "ai_message_id": UUID | None,     # đã persist chưa
            "ai_run_id": UUID | None,
            "error": str | None,
        }
    """
    start_total = time.time()
    timings: dict[str, int] = {}
    error_msg: str | None = None

    # 0. Validate input
    if not user_message or not user_message.strip():
        raise OrchestratorError("user_message is empty")

    # 1. Intent Router (sync, có thể wrap trong to_thread nếu cần)
    t0 = time.time()
    try:
        router_output = classify_intent(
            user_query=user_message,
            history=recent_history or [],
            current_user_id=str(user_id),
            current_conversation_id=str(conversation_id),
        )
    except CircuitBreakerOpen as e:
        # Circuit breaker OPEN → trả về thông báo cho user
        logger.error(f"Router circuit breaker open: {e}")
        timings["router_ms"] = int((time.time() - t0) * 1000)
        return _handle_circuit_breaker_open(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            user_message_id=user_message_id,
            timings=timings,
        )
    except Exception as e:  # noqa: BLE001
        # Router đã có fallback bên trong, đây là defense-in-depth
        logger.exception("Router raised unexpectedly: %s", e)
        # "nếu LLM không phân loại được thì cứ auto Qdrant mà tìm trước"
        router_output = RouterOutput(
            intent="semantic_search",
            confidence=0.3,
            semantic=SemanticBlock(
                collection="quiz_embeddings",
                query=user_message,
                top_k=5,
            ),
            reasoning="Router raised exception, defaulted to semantic_search",
        )
    timings["router_ms"] = int((time.time() - t0) * 1000)
    logger.info(
        f"AI pipeline step 1 (router): {timings['router_ms']}ms, "
        f"intent={router_output.intent}, confidence={router_output.confidence}"
    )

    # 2. Execute tools
    t0 = time.time()
    tool_results = _execute_tools(router_output, current_user_id=user_id)
    timings["tool_ms"] = int((time.time() - t0) * 1000)
    logger.info(
        f"AI pipeline step 2 (tools): {timings['tool_ms']}ms, "
        f"tools={[tr.get('tool') for tr in tool_results]}"
    )

    # 2.5. RAG context: CHỈ chạy khi intent là chat_lookup hoặc semantic_search với chat_context_embeddings
    #      Không cần RAG cho get_my_stats, text_to_sql, etc vì không liên quan đến lịch sử chat.
    t0 = time.time()
    chat_context_rag: list[dict] = []
    
    # Check xem có cần RAG không dựa trên intent
    needs_chat_rag = (
        router_output.semantic
        and router_output.semantic.collection == "chat_context_embeddings"
    )
    
    if needs_chat_rag and getattr(settings, "CHAT_RAG_ENABLED", True):
        try:
            from app.services.search_service import search_messages as _search_messages
            chat_context_rag = _search_messages(
                query=user_message,
                conversation_id=str(conversation_id),
                top_k=settings.CHAT_RAG_TOP_K,
            )
            # Filter theo min score nếu có
            min_score = float(getattr(settings, "CHAT_RAG_MIN_SCORE", 0.0) or 0.0)
            if min_score > 0:
                chat_context_rag = [
                    h for h in chat_context_rag
                    if float(h.get("score") or 0.0) >= min_score
                ]
            logger.info(
                f"Chat RAG triggered: intent={router_output.intent}, "
                f"collection={router_output.semantic.collection}, hits={len(chat_context_rag)}"
            )
        except Exception as e:  # noqa: BLE001
            # RAG fail cũng không phá flow — chỉ log
            logger.warning("RAG chat context retrieval failed: %s", e)
    else:
        logger.debug(
            f"Chat RAG skipped: intent={router_output.intent}, "
            f"needs_chat_rag={needs_chat_rag}"
        )
    
    timings["rag_ms"] = int((time.time() - t0) * 1000)

    # 3. Composer (LLM call #2)
    t0 = time.time()
    try:
        composer_result = _compose_answer(
            user_query=user_message,
            intent=router_output.intent,
            tool_results=tool_results,
            recent_history=recent_history or [],
            chat_context_rag=chat_context_rag,
        )
    except CircuitBreakerOpen as e:
        # Composer circuit breaker OPEN → fallback message
        logger.error(f"Composer circuit breaker open: {e}")
        composer_result = {
            "answer": (
                "Xin lỗi, hiện tại trợ lý AI đang quá tải. "
                "Bạn thử lại sau ít phút nhé."
            ),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": f"composer_circuit_open: {e}",
            "truncated": False,
        }
    timings["composer_ms"] = int((time.time() - t0) * 1000)
    logger.info(
        f"AI pipeline step 3 (composer): {timings['composer_ms']}ms, "
        f"tokens={composer_result.get('usage', {}).get('total_tokens', 0)}"
    )

    if composer_result.get("error"):
        error_msg = composer_result["error"]

    answer_text = composer_result["answer"]
    timings["total_ms"] = int((time.time() - start_total) * 1000)

    # 3.5. Nếu bị truncated do max_tokens, gắn suffix cảnh báo + log
    if composer_result.get("truncated"):
        answer_text = (
            answer_text.rstrip()
            + "\n\n⚠️ _(Câu trả lời bị cắt do giới hạn output. "
              "Bạn có thể hỏi tiếp để tôi nói rõ hơn.)_"
        )
        logger.warning(
            f"Answer truncated (rag_hits={len(chat_context_rag)}, "
            f"max_tokens={composer_result.get('max_tokens_used')}). "
            f"User may need to ask follow-up."
        )

    # 4. Persist AI message (best-effort)
    ai_message_id: UUID | None = None
    try:
        ai_msg_data = MessageCreate(
            content=answer_text,
            metadata={
                "intent": router_output.intent,
                "confidence": router_output.confidence,
                "tool_results_summary": [
                    {
                        "tool": tr.get("tool"),
                        "source": tr.get("source"),
                        "success": tr.get("success"),
                    }
                    for tr in tool_results
                ],
                "model": settings.LLM_MODEL,
                "truncated": composer_result.get("truncated", False),
                "rag_hits": len(chat_context_rag),
            },
        )
        # Sender là user hiện tại (AI reply được attribute cho user kích hoạt)
        # Hoặc có thể tạo system user — tuỳ design
        ai_msg = MessageService.create_message(
            db=db,
            conversation_id=conversation_id,
            sender_id=user_id,
            data=ai_msg_data,
        )
        # Set sender_type=ai + is_ai_generated=True
        from app.models.social.messages import Message
        db.query(Message).filter(Message.id == ai_msg["id"]).update({
            "sender_type": "ai",
            "is_ai_generated": True,
        })
        db.commit()
        ai_message_id = UUID(ai_msg["id"])
        logger.info(f"AI message persisted: {ai_message_id}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Failed to persist AI message: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        # Vẫn return answer để UX không bị block

    # 5. Audit (best-effort, không ảnh hưởng response)
    _write_ai_run_audit(
        db=db,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        ai_message_id=ai_message_id,
        router_output=router_output,
        tool_results=tool_results,
        composer_result=composer_result,
        router_retries=0,  # router đã retry internally
        timings=timings,
        error=error_msg,
    )

    logger.info(
        f"AI pipeline done: total={timings['total_ms']}ms, "
        f"intent={router_output.intent}, "
        f"answer_len={len(answer_text)}"
    )

    return {
        "answer": answer_text,
        "intent": router_output.intent,
        "confidence": router_output.confidence,
        "tool_results": tool_results,
        "chat_context_rag": chat_context_rag,  # top-5 hits từ Qdrant chat
        "ai_message_id": ai_message_id,
        "truncated": composer_result.get("truncated", False),
        "timings": timings,
        "error": error_msg,
        "router_reasoning": router_output.reasoning,
    }


# ---------------------------------------------------------------------------
# Async wrapper (cho WebSocket context)
# ---------------------------------------------------------------------------


async def run_ai_orchestrator_async(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    user_message: str,
    user_message_id: UUID,
    recent_history: list[dict] | None = None,
) -> dict:
    """
    Async wrapper — chạy sync orchestrator trong thread pool.
    Dùng trong FastAPI WebSocket handler / async endpoint.
    """
    return await asyncio.to_thread(
        run_ai_orchestrator,
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
        user_message=user_message,
        user_message_id=user_message_id,
        recent_history=recent_history,
    )
