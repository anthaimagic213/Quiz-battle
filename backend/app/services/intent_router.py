"""
Intent Router - Phân loại ý định user và extract parameters.
Sử dụng LLM call riêng với temperature=0, JSON mode, few-shot examples.
"""

import json
import logging
import re
from typing import Any

from app.schemas.ai import RouterOutput, SemanticBlock
from app.services.llm_service import chat_completion, LLMError, CircuitBreakerOpen
from app.services.llm_error_handler import CircuitBreakerOpen as CBOpen
from app.services.schema_catalog import get_schema_catalog
from app.services.function_schemas import (
    get_router_function_schema,
    convert_function_call_to_router_output,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


# System prompt cho router
ROUTER_SYSTEM_PROMPT = """Bạn là Intent Router cho Quiz Battle — một chatbot giúp user tìm quiz, câu hỏi, thống kê game.

Nhiệm vụ: phân loại câu hỏi của user và extract tham số trả về JSON.

## Intents (chỉ được chọn 1)

- "smalltalk": chào hỏi, hỏi giờ, hỏi cảm ơn, không liên quan quiz/user/stats
- "semantic_search": tìm quiz/question theo chủ đề ngữ nghĩa ("quiz về động vật", "câu hỏi về lịch sử")
- "text_to_sql": truy vấn có cấu trúc (đếm, lọc theo số, thống kê, top X, sắp xếp)
- "hybrid": cần cả 2 (VD: "quiz về X có trên N câu hỏi")
- "get_my_quizzes": user hỏi về quiz của chính họ
- "get_my_stats": user hỏi về thống kê game của chính họ
- "get_my_friends": user hỏi về danh sách bạn bè
- "clarify": không chắc user muốn gì

## Schema Catalog (WHITELIST DUY NHẤT cho text_to_sql)

{catalog_json}

## QUY TẮC BẮT BUỘC

1. CHỈ được select/filter cột có trong schema catalog. KHÔNG được truy vấn bảng khác.
2. KHÔNG tự sinh SQL string. CHỈ trả structured query (tables, columns, filters, etc.).
3. Khi user hỏi về data của chính họ → dùng "get_my_*" intent. KHÔNG cần truyền user_id (backend tự inject).
4. Cột nhạy cảm (email, password_hash) KHÔNG BAO GIỜ được select.
5. Limit mặc định 20, tối đa 50.
6. Placeholder hợp lệ: `<current_user_id>`, `<current_time>`, `<last_24_hours>`, `<last_7_days>`, `<last_30_days>`.
7. Operator hợp lệ: =, !=, >, >=, <, <=, IN, NOT IN, LIKE, ILIKE, IS NULL, IS NOT NULL.
8. Khi không chắc chắn → set confidence < 0.6 để orchestrator fallback sang clarify.
9. Khi user hỏi về NỘI DUNG CHAT trước đó ("ai nói gì về X", "X định làm gì", "có ai nhắc đến Y không") → collection PHẢI là "chat_context_embeddings" và BẮT BUỘC truyền `conversation_id`: "<current_conversation_id>". Backend sẽ auto-inject UUID thật.

## Ví dụ

User: "Chào bạn"
→ {{"intent": "smalltalk", "confidence": 0.99, "semantic": null, "sql": null, "merge_strategy": null, "reasoning": "Chào hỏi xã giao"}}

User: "Tìm quiz về động vật"
→ {{"intent": "semantic_search", "confidence": 0.95, "semantic": {{"collection": "quiz_embeddings", "query": "động vật", "top_k": 5}}, "sql": null, "merge_strategy": null, "reasoning": "Tìm theo chủ đề"}}

User: "Anh Long định chơi quiz gì vậy?"
→ {{"intent": "semantic_search", "confidence": 0.85, "semantic": {{"collection": "chat_context_embeddings", "query": "anh Long quiz", "top_k": 5, "conversation_id": "<current_conversation_id>"}}, "sql": null, "merge_strategy": null, "reasoning": "Hỏi về nội dung chat trước đó → dùng chat_context_embeddings"}}

User: "Có ai nói gì về bóng đá không?"
→ {{"intent": "semantic_search", "confidence": 0.9, "semantic": {{"collection": "chat_context_embeddings", "query": "bóng đá", "top_k": 5, "conversation_id": "<current_conversation_id>"}}, "sql": null, "merge_strategy": null, "reasoning": "Hỏi về nội dung chat → chat_context_embeddings"}}

User: "Top 5 user thắng nhiều nhất"
→ {{"intent": "text_to_sql", "confidence": 0.92, "semantic": null, "sql": {{"tables": ["users", "user_stats"], "joins": ["users__user_stats"], "select": ["users.username", "user_stats.wins"], "filters": [], "order_by": [{{"column": "user_stats.wins", "direction": "DESC"}}], "limit": 5}}, "merge_strategy": null, "reasoning": "Thống kê top user"}}

User: "Quiz về lịch sử Việt Nam có trên 20 câu hỏi"
→ {{"intent": "hybrid", "confidence": 0.88, "semantic": {{"collection": "quiz_embeddings", "query": "lịch sử Việt Nam", "top_k": 10}}, "sql": {{"tables": ["quizzes", "questions"], "joins": ["quizzes__questions"], "select": ["quizzes.id", "quizzes.title"], "filters": [{{"column": "quizzes.is_public", "op": "=", "value": true}}, {{"column": "quizzes.is_deleted", "op": "=", "value": false}}], "group_by": ["quizzes.id", "quizzes.title"], "having": [{{"column": "COUNT(questions.id)", "op": ">", "value": 20}}], "order_by": [{{"column": "quizzes.created_at", "direction": "DESC"}}], "limit": 10}}, "merge_strategy": "sql_filter_then_semantic", "reasoning": "Cần cả semantic search và lọc theo số câu hỏi"}}

User: "Quiz của tôi"
→ {{"intent": "get_my_quizzes", "confidence": 0.95, "semantic": null, "sql": null, "merge_strategy": null, "reasoning": "User hỏi quiz của chính họ"}}

User: "Thống kê game của tôi"
→ {{"intent": "get_my_stats", "confidence": 0.94, "semantic": null, "sql": null, "merge_strategy": null, "reasoning": "User hỏi stats cá nhân"}}

User: "Bạn bè của tôi"
→ {{"intent": "get_my_friends", "confidence": 0.93, "semantic": null, "sql": null, "merge_strategy": null, "reasoning": "User hỏi danh sách bạn"}}

## Output format (JSON ONLY, no markdown)

{{
  "intent": "smalltalk|semantic_search|text_to_sql|hybrid|get_my_quizzes|get_my_stats|get_my_friends|clarify",
  "confidence": 0.0-1.0,
  "semantic": null | {{"collection": "quiz_embeddings|question_embeddings|chat_context_embeddings", "query": "...", "top_k": 1-20, "conversation_id": "..."}},
  "sql": null | {{"tables": [...], "joins": [...], "select": [...], "filters": [...], "group_by": [...], "having": [...], "order_by": [...], "limit": 1-50}},
  "merge_strategy": null | "intersect_ids" | "concat" | "sql_filter_then_semantic",
  "reasoning": "1 câu giải thích ngắn"
}}
"""


def _build_catalog_prompt() -> str:
    """Convert schema catalog thành JSON string cho prompt."""
    catalog = get_schema_catalog()
    # Chỉ lấy phần quan trọng để giảm token
    simplified = {
        "tables": {
            name: {
                "description": t["description"],
                "selectable_columns": [
                    col for col, defn in t["columns"].items()
                    if defn.get("selectable", False)
                ],
                "filterable_columns": t["allowed_filters"],
                "orderable_columns": t["allowed_order_by"],
            }
            for name, t in catalog["tables"].items()
        },
        "joins": list(catalog["joins"].keys()),
    }
    return json.dumps(simplified, ensure_ascii=False, indent=2)


def _build_router_messages(
    user_query: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """Build messages list cho router call."""
    catalog_json = _build_catalog_prompt()
    system_prompt = ROUTER_SYSTEM_PROMPT.format(catalog_json=catalog_json)

    messages = [{"role": "system", "content": system_prompt}]

    # Thêm history gần nhất (max 5 message) để có ngữ cảnh
    if history:
        recent = history[-5:]
        for msg in recent:
            role = "user" if msg.get("sender_type") == "user" else "assistant"
            messages.append({
                "role": role,
                "content": msg.get("content", ""),
            })

    messages.append({"role": "user", "content": user_query})

    return messages


def _call_with_function_calling(messages: list[dict]) -> dict:
    """Call LLM với function calling."""
    function_schema = get_router_function_schema()
    
    return chat_completion(
        messages=messages,
        model=settings.INTENT_ROUTER_MODEL,
        temperature=0,
        max_tokens=512,
        tools=[{
            "type": "function",
            "function": function_schema,
        }],
        tool_choice={"type": "function", "function": {"name": "classify_intent"}},
    )


def _call_with_json_mode(messages: list[dict]) -> dict:
    """Call LLM với JSON mode (fallback)."""
    return chat_completion(
        messages=messages,
        model=settings.INTENT_ROUTER_MODEL,
        temperature=0,
        max_tokens=512,
        response_format={"type": "json_object"},
    )


def _parse_function_call_response(response: dict) -> dict:
    """Parse function call response → RouterOutput dict."""
    tool_calls = response.get("tool_calls")
    if not tool_calls or len(tool_calls) == 0:
        raise ValueError("No tool calls in response")
    
    call = tool_calls[0]
    func_name = call["name"]
    arguments = call["arguments"]
    
    if func_name != "classify_intent":
        raise ValueError(f"Unexpected function: {func_name}")
    
    # Convert function call arguments → RouterOutput dict
    return convert_function_call_to_router_output(func_name, arguments)


def _extract_json_from_response(content: str) -> dict:
    """
    Extract JSON từ LLM response.
    LLM đôi khi wrap trong ```json ... ``` hoặc thêm text thừa.
    """
    content = content.strip()

    # Strip markdown code block
    if content.startswith("```"):
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            content = match.group(1)
        else:
            # Fallback: tìm { đầu tiên và } cuối cùng
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                content = content[start:end + 1]

    return json.loads(content)


def classify_intent(
    user_query: str,
    history: list[dict] | None = None,
    current_user_id: str | None = None,
    current_conversation_id: str | None = None,
    use_function_calling: bool = True,
) -> RouterOutput:
    """
    Phân loại intent của user query (sync).
    
    Flow:
    1. Build prompt với catalog + history
    2. Call LLM với function calling (hoặc JSON mode nếu disable)
    3. Parse function call / JSON response
    4. Validate với Pydantic
    5. Retry 1 lần nếu fail
    6. Fallback về semantic_search nếu fail hoàn toàn
    
    Args:
        user_query: câu hỏi của user
        history: list messages gần nhất (optional)
        current_user_id: UUID user hiện tại (chỉ để log, không truyền vào prompt)
        current_conversation_id: UUID conversation hiện tại. Nếu LLM trả về
            conversation_id="<current_conversation_id>" thì auto-inject UUID thật
            (cho phép dùng chat_context_embeddings).
        use_function_calling: True = dùng function calling, False = JSON mode
    
    Returns:
        RouterOutput (validated, không bao giờ raise)
    """
    messages = _build_router_messages(user_query, history)
    max_retries = 2  # 1 lần retry = tổng 2 attempts

    last_error = None
    for attempt in range(max_retries):
        try:
            # Call LLM với function calling hoặc JSON mode
            if use_function_calling:
                response = _call_with_function_calling(messages)
            else:
                response = _call_with_json_mode(messages)

            # Parse response
            if use_function_calling and response.get("tool_calls"):
                raw = _parse_function_call_response(response)
            else:
                # Fallback JSON parsing nếu LLM không gọi function
                content = response["answer"]
                raw = _extract_json_from_response(content)

            total_tokens = (
                response["usage"].get("prompt_tokens", 0)
                + response["usage"].get("completion_tokens", 0)
            )
            logger.info(
                f"Router LLM response (attempt {attempt + 1}): "
                f"tokens={total_tokens}, "
                f"method={'function_calling' if use_function_calling else 'json_mode'}"
            )

            # Validate với Pydantic
            router_output = RouterOutput.model_validate(raw)

            # Inject conversation_id nếu LLM dùng placeholder
            if (
                router_output.semantic
                and router_output.semantic.collection == "chat_context_embeddings"
                and current_conversation_id
            ):
                cid = router_output.semantic.conversation_id
                if not cid or cid == "<current_conversation_id>":
                    router_output.semantic.conversation_id = current_conversation_id

            # Validate bổ sung: nếu intent yêu cầu semantic mà thiếu → auto-fill
            router_output = _validate_intent_blocks(router_output, user_query)

            logger.info(
                f"Router success: intent={router_output.intent}, "
                f"confidence={router_output.confidence}"
            )
            return router_output

        except CircuitBreakerOpen as e:
            # Circuit breaker OPEN → trả về fallback ngay, không retry
            logger.error(f"Router circuit breaker open: {e}")
            return _fallback_router_output(user_query, e)

        except (LLMError, json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning(
                f"Router attempt {attempt + 1} failed: {type(e).__name__}: {e}"
            )
            if attempt < max_retries - 1:
                continue  # retry

    # Fallback: nếu router fail hoàn toàn → default semantic_search
    logger.error(
        f"Router failed after {max_retries} attempts. "
        f"Falling back to semantic_search. Last error: {last_error}"
    )
    return _fallback_router_output(user_query, last_error)


def _validate_intent_blocks(
    output: RouterOutput,
    user_query: str,
) -> RouterOutput:
    """
    Validate bổ sung: intent nào cần block gì.
    Nếu thiếu → tự tạo block mặc định.
    """
    intent = output.intent

    # Các intent cần semantic block
    needs_semantic = intent in ("semantic_search", "hybrid")
    # Các intent cần sql block
    needs_sql = intent in ("text_to_sql", "hybrid", "get_my_quizzes", "get_my_stats", "get_my_friends")

    # Nếu thiếu semantic nhưng cần
    if needs_semantic and not output.semantic:
        output.semantic = SemanticBlock(
            collection="quiz_embeddings",
            query=user_query,
            top_k=5,
        )
        logger.info("Auto-filled missing semantic block")

    # Nếu thiếu sql nhưng cần (thường là get_my_* đã OK vì sql=null)
    # Hybrid mà thiếu sql thì không sao, chỉ chạy semantic

    return output


def _fallback_router_output(
    user_query: str,
    last_error: Exception | None,
) -> RouterOutput:
    """
    Fallback khi router fail hoàn toàn.
    Strategy: mặc định dùng semantic_search với câu query gốc.
    Đây là yêu cầu của bạn: "nếu LLM không phân loại được thì cứ auto Qdrant mà tìm trước".
    """
    logger.warning(
        f"Using fallback router output (semantic_search) for query: {user_query[:100]}"
    )
    return RouterOutput(
        intent="semantic_search",
        confidence=0.5,  # thấp để orchestrator biết là fallback
        semantic=SemanticBlock(
            collection="quiz_embeddings",
            query=user_query,
            top_k=5,
        ),
        sql=None,
        merge_strategy=None,
        reasoning=f"Router failed ({type(last_error).__name__ if last_error else 'unknown'}), defaulted to semantic_search",
    )
