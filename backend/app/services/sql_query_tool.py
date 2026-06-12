"""
Safe SQL Query Tool với retry, fallback Qdrant, và error handling.
Đây là entry point chính cho orchestrator gọi.
"""

import logging
from typing import Any
from uuid import UUID

from app.schemas.ai import SqlBlock, RouterOutput
from app.services.sql_validator import validate_query, CatalogValidationError
from app.services.sql_tool import execute_sql_query, SQLExecutionError
from app.services.search_service import (
    search_quizzes,
    search_questions,
)

logger = logging.getLogger(__name__)


class ToolResult:
    """Kết quả trả về từ tool, có thể là data hoặc error."""
    def __init__(
        self,
        success: bool,
        data: Any = None,
        error: str | None = None,
        source: str = "sql",
        used_fallback: bool = False,
    ):
        self.success = success
        self.data = data
        self.error = error
        self.source = source
        self.used_fallback = used_fallback

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "source": self.source,
            "used_fallback": self.used_fallback,
        }


def tool_safe_sql_query(
    query: SqlBlock,
    current_user_id: UUID | None = None,
    timeout_ms: int = 5000,
) -> dict:
    """
    Tool: thực thi SQL query an toàn với retry + fallback Qdrant.
    
    Flow:
    1. Validate query với schema catalog
    2. Nếu fail validation: return error (không retry - LLM phải tự sửa)
    3. Execute query với timeout
    4. Nếu fail execution: retry 1 lần
    5. Nếu vẫn fail: fallback Qdrant semantic search
    6. Return ToolResult
    
    Returns ToolResult.to_dict()
    """
    # 1. Validate với schema catalog
    try:
        validate_query(query)
    except CatalogValidationError as e:
        logger.warning(f"SQL query failed validation: {e}")
        return ToolResult(
            success=False,
            error=f"Validation failed: {str(e)}",
            source="sql",
            used_fallback=False,
        ).to_dict()

    # 2. Execute (retry 1 lần nếu fail)
    last_error = None
    for attempt in range(2):
        try:
            result = execute_sql_query(
                query=query,
                current_user_id=current_user_id,
                timeout_ms=timeout_ms,
            )
            logger.info(
                f"SQL query success: {result['count']} rows "
                f"in {result['elapsed_ms']}ms (attempt {attempt + 1})"
            )
            return ToolResult(
                success=True,
                data=result,
                source="sql",
                used_fallback=False,
            ).to_dict()
        except SQLExecutionError as e:
            last_error = e
            logger.warning(f"SQL execution failed (attempt {attempt + 1}): {e}")
            if attempt == 0:
                continue  # retry once

    # 3. Fallback Qdrant semantic search
    logger.error(
        f"SQL failed after 2 attempts, falling back to Qdrant. "
        f"Last error: {last_error}"
    )

    fallback_result = _fallback_to_qdrant(query, current_user_id)
    if fallback_result["success"]:
        return fallback_result

    # 4. Cả SQL lẫn Qdrant đều fail
    return ToolResult(
        success=False,
        error=f"SQL failed: {last_error}. Fallback also failed: {fallback_result.get('error')}",
        source="none",
        used_fallback=True,
    ).to_dict()


def _fallback_to_qdrant(
    query: SqlBlock,
    current_user_id: UUID | None,
) -> dict:
    """
    Fallback: khi SQL fail, cố gắng dùng Qdrant semantic search.
    
    Strategy:
    - Nếu query có table 'quizzes' -> search_quizzes với title từ filter LIKE
    - Nếu query có table 'questions' -> search_questions
    - Ngược lại: search chung trên quiz_embeddings
    """
    try:
        # Extract search terms từ filters
        search_terms = _extract_search_terms(query)

        if not search_terms:
            return ToolResult(
                success=False,
                error="No searchable terms in SQL filters for Qdrant fallback",
                source="qdrant_fallback",
            ).to_dict()

        # Choose collection dựa trên table
        if "questions" in query.tables:
            results = search_questions(search_terms, top_k=query.limit)
        else:
            # Mặc định: search quiz
            results = search_quizzes(search_terms, top_k=query.limit)

        return ToolResult(
            success=True,
            data={
                "columns": ["id", "title", "description", "score"],
                "rows": results,
                "count": len(results),
                "elapsed_ms": 0,  # search_service có thể trả timing
                "note": "Result từ Qdrant semantic search (fallback do SQL fail)",
            },
            source="qdrant_fallback",
            used_fallback=True,
        ).to_dict()

    except Exception as e:
        logger.exception(f"Qdrant fallback failed: {e}")
        return ToolResult(
            success=False,
            error=f"Qdrant fallback failed: {str(e)[:200]}",
            source="qdrant_fallback",
        ).to_dict()


def _extract_search_terms(query: SqlBlock) -> str:
    """
    Extract search terms từ SqlBlock filters.
    Tìm các filter LIKE/ILIKE với value string -> ghép thành query string.
    """
    terms = []

    for flt in query.filters:
        if flt.op in ("LIKE", "ILIKE", "=") and isinstance(flt.value, str):
            if flt.op in ("LIKE", "ILIKE"):
                # Strip wildcards
                term = flt.value.strip("%").strip()
            else:
                term = flt.value
            if term and not term.startswith("<"):
                terms.append(term)

    return " ".join(terms) if terms else ""


def tool_hybrid_search(
    router_output: RouterOutput,
    current_user_id: UUID | None = None,
) -> dict:
    """
    Tool: hybrid search (kết hợp SQL filter + Qdrant semantic).
    
    Strategy (theo merge_strategy):
    - "sql_filter_then_semantic" (default): chạy SQL trước lấy whitelist ID,
      rồi semantic search trong Qdrant với filter id IN (...).
    - "intersect_ids": lấy intersection giữa ID set từ SQL và từ Qdrant.
    - "concat": chạy cả 2, nối kết quả.
    """
    if not router_output.sql or not router_output.semantic:
        return ToolResult(
            success=False,
            error="Hybrid requires both sql and semantic blocks",
            source="hybrid",
        ).to_dict()

    # 1. Run SQL filter
    sql_result = tool_safe_sql_query(
        router_output.sql,
        current_user_id=current_user_id,
    )

    sql_ids = set()
    if sql_result["success"] and sql_result["data"]:
        for row in sql_result["data"].get("rows", []):
            if "id" in row:
                sql_ids.add(str(row["id"]))

    # 2. Run Qdrant semantic search
    sem = router_output.semantic
    try:
        if sem.collection == "quiz_embeddings":
            qdrant_results = search_quizzes(sem.query, top_k=sem.top_k)
        elif sem.collection == "question_embeddings":
            qdrant_results = search_questions(sem.query, top_k=sem.top_k)
        else:
            qdrant_results = []
    except Exception as e:
        logger.exception(f"Qdrant search failed in hybrid: {e}")
        qdrant_results = []

    qdrant_ids = set(str(r.get("id")) for r in qdrant_results if r.get("id"))

    # 3. Merge theo strategy
    strategy = router_output.merge_strategy or "sql_filter_then_semantic"

    if strategy == "intersect_ids":
        merged_ids = sql_ids & qdrant_ids
        # Filter qdrant_results theo merged_ids
        merged_results = [r for r in qdrant_results if str(r.get("id")) in merged_ids]
    elif strategy == "concat":
        # Nối: SQL rows trước, Qdrant sau (dedupe by id)
        seen = sql_ids
        merged_results = sql_result["data"]["rows"] if sql_result["success"] else []
        for r in qdrant_results:
            if str(r.get("id")) not in seen:
                merged_results.append(r)
                seen.add(str(r.get("id")))
    else:  # sql_filter_then_semantic
        # Chỉ giữ Qdrant results có id trong SQL ids
        merged_results = [r for r in qdrant_results if str(r.get("id")) in sql_ids]
        if not merged_results and sql_result["success"]:
            # Nếu Qdrant miss hết, fallback trả SQL rows
            merged_results = sql_result["data"]["rows"]

    return ToolResult(
        success=True,
        data={
            "columns": ["id", "title", "description", "score"] if merged_results else [],
            "rows": merged_results,
            "count": len(merged_results),
            "sql_count": len(sql_ids),
            "qdrant_count": len(qdrant_ids),
            "merge_strategy": strategy,
        },
        source="hybrid",
        used_fallback=False,
    ).to_dict()
