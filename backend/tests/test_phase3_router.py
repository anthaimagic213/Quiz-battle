"""
Test Intent Router - mock LLM responses.
Chạy: cd backend && python tests/test_phase3_router.py
"""

import json
from unittest.mock import patch, MagicMock
from app.services.intent_router import classify_intent
from app.schemas.ai import RouterOutput


def test_router_smalltalk():
    """Test phân loại smalltalk."""
    mock_response = {
        "answer": json.dumps({
            "intent": "smalltalk",
            "confidence": 0.99,
            "semantic": None,
            "sql": None,
            "merge_strategy": None,
            "reasoning": "Chao hoi xa giao",
        }),
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "raw": {},
    }
    
    with patch("app.services.intent_router.chat_completion", return_value=mock_response):
        result = classify_intent("Chào bạn")
        
        assert result.intent == "smalltalk"
        assert result.confidence >= 0.9
        assert result.semantic is None
        assert result.sql is None
        print("[OK] Router: smalltalk")


def test_router_semantic_search():
    """Test phân loại semantic_search."""
    mock_response = {
        "answer": json.dumps({
            "intent": "semantic_search",
            "confidence": 0.95,
            "semantic": {
                "collection": "quiz_embeddings",
                "query": "động vật",
                "top_k": 5,
            },
            "sql": None,
            "merge_strategy": None,
            "reasoning": "Tim theo chu de",
        }),
        "usage": {"prompt_tokens": 150, "completion_tokens": 60},
        "raw": {},
    }
    
    with patch("app.services.intent_router.chat_completion", return_value=mock_response):
        result = classify_intent("Tìm quiz về động vật")
        
        assert result.intent == "semantic_search"
        assert result.semantic is not None
        assert result.semantic.collection == "quiz_embeddings"
        assert result.semantic.query == "động vật"
        assert result.semantic.top_k == 5
        print("[OK] Router: semantic_search")


def test_router_text_to_sql():
    """Test phân loại text_to_sql."""
    mock_response = {
        "answer": json.dumps({
            "intent": "text_to_sql",
            "confidence": 0.92,
            "semantic": None,
            "sql": {
                "tables": ["users", "user_stats"],
                "joins": ["users__user_stats"],
                "select": ["users.username", "user_stats.wins"],
                "filters": [],
                "group_by": [],
                "having": [],
                "order_by": [{"column": "user_stats.wins", "direction": "DESC"}],
                "limit": 5,
            },
            "merge_strategy": None,
            "reasoning": "Thong ke top user",
        }),
        "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        "raw": {},
    }
    
    with patch("app.services.intent_router.chat_completion", return_value=mock_response):
        result = classify_intent("Top 5 user thắng nhiều nhất")
        
        assert result.intent == "text_to_sql"
        assert result.sql is not None
        assert result.sql.tables == ["users", "user_stats"]
        assert result.sql.joins == ["users__user_stats"]
        assert len(result.sql.select) == 2
        print("[OK] Router: text_to_sql")


def test_router_fallback_on_llm_error():
    """Test fallback về semantic_search khi LLM fail."""
    with patch("app.services.intent_router.chat_completion", side_effect=Exception("LLM timeout")):
        result = classify_intent("Tìm quiz")
        
        # Should fallback to semantic_search
        assert result.intent == "semantic_search"
        assert result.confidence < 0.6  # Low confidence = fallback
        assert result.semantic is not None
        assert result.semantic.query == "Tìm quiz"
        assert "failed" in result.reasoning.lower()
        print("[OK] Router: fallback on error")


def test_router_fallback_on_invalid_json():
    """Test fallback khi LLM trả JSON invalid."""
    mock_response = {
        "answer": "This is not JSON",
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        "raw": {},
    }
    
    with patch("app.services.intent_router.chat_completion", return_value=mock_response):
        result = classify_intent("Something unclear")
        
        # Should fallback to semantic_search
        assert result.intent == "semantic_search"
        assert result.confidence < 0.6
        print("[OK] Router: fallback on invalid JSON")


def test_router_auto_fill_missing_semantic():
    """Test auto-fill semantic block nếu intent cần nhưng thiếu."""
    mock_response = {
        "answer": json.dumps({
            "intent": "semantic_search",
            "confidence": 0.88,
            "semantic": None,  # Thiếu!
            "sql": None,
            "merge_strategy": None,
            "reasoning": "Missing semantic block",
        }),
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        "raw": {},
    }
    
    with patch("app.services.intent_router.chat_completion", return_value=mock_response):
        result = classify_intent("Quiz về lịch sử")
        
        # Should auto-fill semantic
        assert result.intent == "semantic_search"
        assert result.semantic is not None
        assert result.semantic.query == "Quiz về lịch sử"
        assert result.semantic.top_k == 5
        print("[OK] Router: auto-fill missing semantic")


if __name__ == "__main__":
    print("=== Test Intent Router ===\n")
    
    test_router_smalltalk()
    test_router_semantic_search()
    test_router_text_to_sql()
    test_router_fallback_on_llm_error()
    test_router_fallback_on_invalid_json()
    test_router_auto_fill_missing_semantic()
    
    print("\n=== All router tests passed ===")
