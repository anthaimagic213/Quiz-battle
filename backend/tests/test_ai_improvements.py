"""
Test script để verify:
1. Nới lỏng whitelist SQL (aggregate, date functions, new tables)
2. Function calling thay JSON parsing
3. Circuit breaker và error handling

Usage:
    python -m pytest backend/tests/test_ai_improvements.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.schema_catalog import (
    get_schema_catalog,
    is_table_allowed,
    ALLOWED_AGGREGATES,
    ALLOWED_DATE_FUNCTIONS,
    MAX_JOINS,
)
from app.services.sql_validator import validate_query, CatalogValidationError
from app.services.llm_error_handler import (
    CircuitBreaker,
    CircuitState,
    retry_with_backoff,
    call_with_resilience,
    CircuitBreakerOpen,
)
from app.services.function_schemas import (
    get_router_function_schema,
    convert_function_call_to_router_output,
)
from app.schemas.ai import SqlBlock, FilterBlock, OrderByBlock


class TestSchemaExpansion:
    """Test nới rộng schema catalog."""
    
    def test_new_tables_added(self):
        """Check các bảng mới đã được thêm."""
        catalog = get_schema_catalog()
        new_tables = ["tags", "quizzes_tags", "user_achievements", "notifications", "room_players"]
        
        for table in new_tables:
            assert table in catalog["tables"], f"Table '{table}' missing"
            assert is_table_allowed(table), f"Table '{table}' not allowed"
    
    def test_new_joins_added(self):
        """Check các join mới."""
        catalog = get_schema_catalog()
        new_joins = [
            "quizzes__tags",
            "tags__quizzes_tags",
            "users__achievements",
            "users__notifications",
            "game_rooms__room_players",
            "users__room_players",
        ]
        
        for join_name in new_joins:
            assert join_name in catalog["joins"], f"Join '{join_name}' missing"
    
    def test_aggregate_functions_whitelist(self):
        """Check aggregate functions được phép."""
        assert "COUNT" in ALLOWED_AGGREGATES
        assert "SUM" in ALLOWED_AGGREGATES
        assert "AVG" in ALLOWED_AGGREGATES
        assert "MIN" in ALLOWED_AGGREGATES
        assert "MAX" in ALLOWED_AGGREGATES
        assert "COUNT(*)" in ALLOWED_AGGREGATES
    
    def test_date_functions_whitelist(self):
        """Check date functions được phép."""
        assert "DATE_TRUNC" in ALLOWED_DATE_FUNCTIONS
        assert "EXTRACT" in ALLOWED_DATE_FUNCTIONS
        assert "NOW" in ALLOWED_DATE_FUNCTIONS


class TestSQLValidator:
    """Test SQL validator với aggregate và date functions."""
    
    def test_validate_aggregate_count_star(self):
        """Validate COUNT(*)."""
        query = SqlBlock(
            tables=["quizzes"],
            joins=[],
            select=["COUNT(*) AS total"],
            filters=[
                FilterBlock(column="is_public", op="=", value=True),
            ],
            limit=1,
        )
        # Không raise exception
        validate_query(query)
    
    def test_validate_aggregate_sum(self):
        """Validate SUM(column)."""
        query = SqlBlock(
            tables=["user_stats"],
            joins=[],
            select=["SUM(user_stats.total_score) AS total"],
            filters=[],
            limit=10,
        )
        validate_query(query)
    
    def test_validate_date_trunc(self):
        """Validate DATE_TRUNC."""
        query = SqlBlock(
            tables=["quizzes"],
            joins=[],
            select=["DATE_TRUNC('day', quizzes.created_at) AS day", "COUNT(*) AS count"],
            filters=[],
            group_by=["DATE_TRUNC('day', quizzes.created_at)"],
            limit=30,
        )
        validate_query(query)
    
    def test_max_joins_exceeded(self):
        """Check MAX_JOINS enforcement."""
        # Tạo query với > MAX_JOINS
        query = SqlBlock(
            tables=["quizzes", "questions", "game_rooms", "users"],
            joins=["quizzes__questions", "quizzes__game_rooms", "users__user_stats", "users__friendships_1"],
            select=["quizzes.title"],
            filters=[],
            limit=10,
        )
        
        with pytest.raises(CatalogValidationError, match="Too many joins"):
            validate_query(query)
    
    def test_require_limit(self):
        """Check LIMIT bắt buộc."""
        query = SqlBlock(
            tables=["quizzes"],
            joins=[],
            select=["id", "title"],
            filters=[],
            limit=0,  # invalid
        )
        
        with pytest.raises(CatalogValidationError, match="LIMIT is required"):
            validate_query(query)


class TestCircuitBreaker:
    """Test circuit breaker pattern."""
    
    def test_circuit_starts_closed(self):
        """Circuit breaker bắt đầu ở trạng thái CLOSED."""
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
    
    def test_circuit_opens_after_failures(self):
        """Circuit OPEN sau khi vượt ngưỡng fail."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        
        def failing_func():
            raise RuntimeError("fail")
        
        # 3 lần fail
        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)
        
        # Circuit phải OPEN
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3
    
    def test_circuit_blocks_when_open(self):
        """Circuit OPEN block các calls tiếp theo."""
        cb = CircuitBreaker(name="test", failure_threshold=2)
        
        def failing_func():
            raise RuntimeError("fail")
        
        # Trigger OPEN
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_func)
        
        # Call tiếp theo phải bị block
        with pytest.raises(CircuitBreakerOpen):
            cb.call(failing_func)
    
    def test_circuit_resets_on_success(self):
        """Circuit reset về CLOSED khi call thành công."""
        cb = CircuitBreaker(name="test", failure_threshold=3)
        
        def success_func():
            return "ok"
        
        # 1 lần fail
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        
        assert cb.failure_count == 1
        
        # Success → reset
        result = cb.call(success_func)
        assert result == "ok"
        assert cb.failure_count == 0


class TestRetryLogic:
    """Test retry với exponential backoff."""
    
    def test_retry_succeeds_after_failures(self):
        """Retry thành công sau vài lần fail."""
        counter = {"attempts": 0}
        
        def flaky_func():
            counter["attempts"] += 1
            if counter["attempts"] < 3:
                raise RuntimeError("transient error")
            return "success"
        
        result = retry_with_backoff(
            flaky_func,
            max_retries=3,
            initial_delay=0.01,  # fast for test
        )
        
        assert result == "success"
        assert counter["attempts"] == 3
    
    def test_retry_exhausted(self):
        """Retry hết lần thử → raise exception cuối."""
        def always_fail():
            raise RuntimeError("permanent error")
        
        with pytest.raises(RuntimeError, match="permanent error"):
            retry_with_backoff(
                always_fail,
                max_retries=2,
                initial_delay=0.01,
            )


class TestFunctionCalling:
    """Test function calling schemas."""
    
    def test_router_function_schema_structure(self):
        """Check router function schema có đầy đủ fields."""
        schema = get_router_function_schema()
        
        assert schema["name"] == "classify_intent"
        assert "description" in schema
        assert "parameters" in schema
        
        params = schema["parameters"]
        assert params["type"] == "object"
        assert "intent" in params["properties"]
        assert "confidence" in params["properties"]
        assert "reasoning" in params["properties"]
        
        # Check intent enum
        intent_enum = params["properties"]["intent"]["enum"]
        assert "smalltalk" in intent_enum
        assert "semantic_search" in intent_enum
        assert "text_to_sql" in intent_enum
        assert "hybrid" in intent_enum
        assert "chat_lookup" in intent_enum
    
    def test_convert_function_call_simple(self):
        """Test convert function call → RouterOutput."""
        arguments = {
            "intent": "smalltalk",
            "confidence": 0.95,
            "reasoning": "User chào hỏi",
        }
        
        result = convert_function_call_to_router_output("classify_intent", arguments)
        
        assert result["intent"] == "smalltalk"
        assert result["confidence"] == 0.95
        assert result["reasoning"] == "User chào hỏi"
        assert result["semantic"] is None
        assert result["sql"] is None
    
    def test_convert_function_call_with_semantic(self):
        """Test convert với semantic block."""
        arguments = {
            "intent": "semantic_search",
            "confidence": 0.88,
            "reasoning": "Tìm quiz theo chủ đề",
            "semantic_collection": "quiz_embeddings",
            "semantic_query": "động vật",
            "semantic_top_k": 5,
        }
        
        result = convert_function_call_to_router_output("classify_intent", arguments)
        
        assert result["semantic"]["collection"] == "quiz_embeddings"
        assert result["semantic"]["query"] == "động vật"
        assert result["semantic"]["top_k"] == 5
    
    def test_convert_function_call_with_sql(self):
        """Test convert với SQL block."""
        arguments = {
            "intent": "text_to_sql",
            "confidence": 0.92,
            "reasoning": "Đếm quiz",
            "sql_tables": ["quizzes"],
            "sql_select": ["COUNT(*) AS total"],
            "sql_filters": [
                {"column": "is_public", "op": "=", "value": True},
            ],
            "sql_limit": 1,
        }
        
        result = convert_function_call_to_router_output("classify_intent", arguments)
        
        assert result["sql"]["tables"] == ["quizzes"]
        assert result["sql"]["select"] == ["COUNT(*) AS total"]
        assert len(result["sql"]["filters"]) == 1
        assert result["sql"]["limit"] == 1


class TestResilience:
    """Test tích hợp circuit breaker + retry."""
    
    def test_call_with_resilience_success(self):
        """Test resilience wrapper với function thành công."""
        def success_func():
            return "ok"
        
        result = call_with_resilience(
            success_func,
            circuit_breaker_name="test_resilience",
            max_retries=2,
        )
        
        assert result == "ok"
    
    def test_call_with_resilience_with_fallback(self):
        """Test resilience với fallback khi fail."""
        def always_fail():
            raise RuntimeError("fail")
        
        def fallback():
            return "fallback_value"
        
        result = call_with_resilience(
            always_fail,
            circuit_breaker_name="test_fallback",
            max_retries=1,
            fallback=fallback,
        )
        
        assert result == "fallback_value"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
