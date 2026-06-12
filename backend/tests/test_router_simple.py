"""
Test Intent Router - unit test với mock.
Chạy: cd backend && set PYTHONPATH=. && python tests/test_router_simple.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

# Mock settings trước khi import bất cứ thứ gì
from unittest.mock import MagicMock, patch
import app.core.config as cfg

mock_settings = MagicMock()
mock_settings.LLM_MODEL = "gemini-2.5-flash"
mock_settings.INTENT_ROUTER_MODEL = "gemini-2.5-flash"
cfg.settings = mock_settings

import json
from app.services.intent_router import classify_intent


print("=== Test Intent Router (Mock LLM) ===\n")

# Test 1: Smalltalk
print("[1/6] Test smalltalk...")
mock_resp = {
    "answer": '{"intent":"smalltalk","confidence":0.99,"semantic":null,"sql":null,"merge_strategy":null,"reasoning":"Chao"}',
    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
}
with patch("app.services.intent_router.chat_completion", return_value=mock_resp):
    result = classify_intent("Chào bạn")
    assert result.intent == "smalltalk"
    print("[OK] Smalltalk")

# Test 2: Semantic search
print("[2/6] Test semantic_search...")
mock_resp = {
    "answer": '{"intent":"semantic_search","confidence":0.95,"semantic":{"collection":"quiz_embeddings","query":"dong vat","top_k":5},"sql":null,"merge_strategy":null,"reasoning":"Tim"}',
    "usage": {"prompt_tokens": 150, "completion_tokens": 60},
}
with patch("app.services.intent_router.chat_completion", return_value=mock_resp):
    result = classify_intent("Tìm quiz về động vật")
    assert result.intent == "semantic_search"
    assert result.semantic.query == "dong vat"
    print("[OK] Semantic search")

# Test 3: Text-to-SQL
print("[3/6] Test text_to_sql...")
mock_resp = {
    "answer": '{"intent":"text_to_sql","confidence":0.92,"semantic":null,"sql":{"tables":["users","user_stats"],"joins":["users__user_stats"],"select":["users.username","user_stats.wins"],"filters":[],"group_by":[],"having":[],"order_by":[{"column":"user_stats.wins","direction":"DESC"}],"limit":5},"merge_strategy":null,"reasoning":"Top"}',
    "usage": {"prompt_tokens": 200, "completion_tokens": 100},
}
with patch("app.services.intent_router.chat_completion", return_value=mock_resp):
    result = classify_intent("Top 5 user")
    assert result.intent == "text_to_sql"
    assert result.sql is not None
    print("[OK] Text-to-SQL")

# Test 4: LLM error → fallback semantic_search
print("[4/6] Test LLM error fallback...")
with patch("app.services.intent_router.chat_completion", side_effect=Exception("LLM timeout")):
    result = classify_intent("Tìm quiz")
    assert result.intent == "semantic_search"
    assert result.confidence < 0.6
    assert "failed" in result.reasoning.lower()
    print("[OK] Fallback on LLM error")

# Test 5: Invalid JSON → fallback
print("[5/6] Test invalid JSON fallback...")
mock_resp = {"answer": "Not JSON at all", "usage": {}}
with patch("app.services.intent_router.chat_completion", return_value=mock_resp):
    result = classify_intent("Something")
    assert result.intent == "semantic_search"
    print("[OK] Fallback on invalid JSON")

# Test 6: Auto-fill missing semantic block
print("[6/6] Test auto-fill semantic...")
mock_resp = {
    "answer": '{"intent":"semantic_search","confidence":0.88,"semantic":null,"sql":null,"merge_strategy":null,"reasoning":"Missing"}',
    "usage": {"prompt_tokens": 120, "completion_tokens": 40},
}
with patch("app.services.intent_router.chat_completion", return_value=mock_resp):
    result = classify_intent("Quiz về lịch sử")
    assert result.intent == "semantic_search"
    assert result.semantic is not None  # Auto-filled
    assert result.semantic.query == "Quiz về lịch sử"
    print("[OK] Auto-fill semantic")

print("\n=== All 6 router tests PASSED ===")
