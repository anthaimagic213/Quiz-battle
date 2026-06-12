"""
Function Calling Schemas cho LLM (Gemini/OpenAI format).

Thay thế JSON parsing bằng native tool use.
LLM sẽ gọi function với parameters validated tự động.
"""

from typing import Any


def get_router_function_schema() -> dict[str, Any]:
    """
    Function schema cho Intent Router.
    LLM sẽ gọi function classify_intent() với parameters.
    """
    return {
        "name": "classify_intent",
        "description": (
            "Phân loại ý định của user và extract parameters cho Quiz Battle chatbot. "
            "Chatbot giúp user tìm quiz, câu hỏi, thống kê game, và trả lời câu hỏi về nội dung chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "smalltalk",
                        "semantic_search",
                        "text_to_sql",
                        "hybrid",
                        "get_my_quizzes",
                        "get_my_stats",
                        "get_my_friends",
                        "chat_lookup",
                        "clarify",
                    ],
                    "description": (
                        "Intent của user:\n"
                        "- smalltalk: chào hỏi, xã giao, không liên quan quiz/game\n"
                        "- semantic_search: tìm quiz/question theo chủ đề ngữ nghĩa\n"
                        "- text_to_sql: truy vấn có cấu trúc (đếm, lọc, thống kê, top X)\n"
                        "- hybrid: cần cả semantic và SQL (VD: quiz về X có > N câu)\n"
                        "- get_my_quizzes: user hỏi về quiz của chính họ\n"
                        "- get_my_stats: user hỏi về thống kê game của chính họ\n"
                        "- get_my_friends: user hỏi về bạn bè\n"
                        "- chat_lookup: user hỏi về NỘI DUNG CHAT trước đó (ai nói gì, X định làm gì)\n"
                        "- clarify: không chắc user muốn gì"
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": "Độ tin cậy 0.0-1.0. Nếu < 0.6 → clarify",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "semantic_collection": {
                    "type": "string",
                    "enum": [
                        "quiz_embeddings",
                        "question_embeddings",
                        "chat_context_embeddings",
                    ],
                    "description": (
                        "Collection Qdrant cần search:\n"
                        "- quiz_embeddings: tìm quiz theo chủ đề\n"
                        "- question_embeddings: tìm câu hỏi\n"
                        "- chat_context_embeddings: tìm tin nhắn chat trước đó (PHẢI dùng khi intent=chat_lookup)"
                    ),
                },
                "semantic_query": {
                    "type": "string",
                    "description": "Query string cho semantic search (nếu intent cần semantic)",
                },
                "semantic_top_k": {
                    "type": "integer",
                    "description": "Số kết quả semantic cần lấy (1-20)",
                    "minimum": 1,
                    "maximum": 20,
                },
                "conversation_id_needed": {
                    "type": "boolean",
                    "description": (
                        "True nếu search chat_context_embeddings (backend sẽ inject UUID thật). "
                        "Bắt buộc True khi intent=chat_lookup."
                    ),
                },
                "sql_tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Danh sách bảng cần query (nếu intent cần SQL)",
                },
                "sql_joins": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Danh sách join names từ catalog (tối đa 3)",
                },
                "sql_select": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Columns cần select. Có thể có:\n"
                        "- table.column\n"
                        "- COUNT(*)\n"
                        "- COUNT(table.column)\n"
                        "- SUM/AVG/MIN/MAX(table.column)\n"
                        "- DATE_TRUNC('day', table.created_at)\n"
                        "- EXTRACT(YEAR FROM table.created_at)"
                    ),
                },
                "sql_filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "op": {
                                "type": "string",
                                "enum": ["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "LIKE", "ILIKE", "IS NULL", "IS NOT NULL"],
                            },
                            "value": {
                                "description": (
                                    "Giá trị filter. Có thể là:\n"
                                    "- string, number, boolean\n"
                                    "- array (cho IN/NOT IN)\n"
                                    "- null (cho IS NULL/IS NOT NULL)\n"
                                    "- placeholder: <current_user_id>, <last_7_days>, <last_30_days>"
                                ),
                            },
                        },
                        "required": ["column", "op"],
                    },
                },
                "sql_group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns cho GROUP BY",
                },
                "sql_having": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {
                                "type": "string",
                                "description": "Aggregate expression: COUNT(*), SUM(table.col)",
                            },
                            "op": {"type": "string"},
                            "value": {},
                        },
                        "required": ["column", "op", "value"],
                    },
                },
                "sql_order_by": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "direction": {
                                "type": "string",
                                "enum": ["ASC", "DESC"],
                            },
                        },
                        "required": ["column", "direction"],
                    },
                },
                "sql_limit": {
                    "type": "integer",
                    "description": "LIMIT (bắt buộc, tối đa 50)",
                    "minimum": 1,
                    "maximum": 50,
                },
                "merge_strategy": {
                    "type": "string",
                    "enum": [
                        "intersect_ids",
                        "concat",
                        "sql_filter_then_semantic",
                    ],
                    "description": "Cách merge khi intent=hybrid",
                },
                "reasoning": {
                    "type": "string",
                    "description": "1 câu giải thích ngắn tại sao chọn intent này",
                },
            },
            "required": ["intent", "confidence", "reasoning"],
        },
    }


def get_sql_query_function_schema() -> dict[str, Any]:
    """
    Function schema cho SQL query builder (future use).
    LLM có thể gọi trực tiếp build_sql_query() thay vì trả struct.
    """
    return {
        "name": "build_sql_query",
        "description": "Build SQL query an toàn từ natural language (whitelist enforced)",
        "parameters": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": [
                        "count_quizzes",
                        "list_quizzes",
                        "top_users",
                        "user_stats",
                        "quiz_with_tags",
                        "room_stats",
                        "custom",
                    ],
                    "description": "Loại query (template có sẵn hoặc custom)",
                },
                "filters": {
                    "type": "object",
                    "description": "Key-value filters (user_id, created_after, is_public...)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
                "order_by": {
                    "type": "string",
                    "description": "Column để sort",
                },
                "order_direction": {
                    "type": "string",
                    "enum": ["ASC", "DESC"],
                },
            },
            "required": ["query_type"],
        },
    }


def convert_function_call_to_router_output(
    func_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert function call arguments → RouterOutput dict.
    
    Args:
        func_name: tên function (phải là "classify_intent")
        arguments: dict arguments từ LLM
    
    Returns:
        dict tương thích RouterOutput schema
    """
    if func_name != "classify_intent":
        raise ValueError(f"Unknown function: {func_name}")
    
    intent = arguments["intent"]
    confidence = arguments["confidence"]
    reasoning = arguments.get("reasoning", "")
    
    # Build semantic block
    semantic = None
    if any(k in arguments for k in ["semantic_collection", "semantic_query"]):
        semantic = {
            "collection": arguments.get("semantic_collection", "quiz_embeddings"),
            "query": arguments.get("semantic_query", ""),
            "top_k": arguments.get("semantic_top_k", 5),
        }
        # Inject conversation_id placeholder nếu cần
        if arguments.get("conversation_id_needed"):
            semantic["conversation_id"] = "<current_conversation_id>"
    
    # Build SQL block
    sql = None
    if any(k.startswith("sql_") for k in arguments):
        sql = {
            "tables": arguments.get("sql_tables", []),
            "joins": arguments.get("sql_joins", []),
            "select": arguments.get("sql_select", []),
            "filters": arguments.get("sql_filters", []),
            "group_by": arguments.get("sql_group_by", []),
            "having": arguments.get("sql_having", []),
            "order_by": arguments.get("sql_order_by", []),
            "limit": arguments.get("sql_limit", 20),
        }
    
    return {
        "intent": intent,
        "confidence": confidence,
        "semantic": semantic,
        "sql": sql,
        "merge_strategy": arguments.get("merge_strategy"),
        "reasoning": reasoning,
    }
