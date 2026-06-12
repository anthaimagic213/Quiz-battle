"""
Debug script - test từng layer của AI pipeline.
Chạy: cd backend && python debug_ai.py

Lưu ý: nên chạy bên trong Docker container (nơi có đủ fastapi, psycopg2,
postgres, qdrant). Hoặc cài các package thiếu vào venv + chạy Postgres/Qdrant local.

Có thể truyền user_id / conversation_id qua CLI để test với data có sẵn:
    python debug_ai.py --user-id <uuid> --conv-id <uuid>
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.abspath('.'))

# ---------------------------------------------------------------------------
# Pre-load TẤT CẢ models trước khi bất kỳ test nào chạy.
# Lý do: các model dùng `relationship("OtherModel", ...)` (string form).
# Khi SQLAlchemy configure mapper cho User, nó cần resolve "RefreshToken",
# "Quiz", ... trong registry. Nếu thiếu 1 model nào đó → InvalidRequestError.
# Import `app.db.base` sẽ load đầy đủ mọi model cùng lúc.
# ---------------------------------------------------------------------------
try:
    import app.db.base  # noqa: F401  (side-effect: register all mappers)
    print("[init] All models registered via app.db.base")
except Exception as e:
    print(f"[WARN] Could not pre-load models: {e}\n")

# ---------------------------------------------------------------------------
# Parse CLI args
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Debug AI pipeline")
parser.add_argument("--user-id", default=None, help="UUID của user có sẵn trong DB")
parser.add_argument("--conv-id", default=None, help="UUID của conversation có sẵn trong DB")
parser.add_argument("--text", default="Tìm quiz về động vật", help="Câu user giả lập")
args = parser.parse_args()

# Test 1: Config
print("=== [1/5] Test config ===")
try:
    from app.core.config import settings
    print(f"[OK] LLM_MODEL = {settings.LLM_MODEL}")
    print(f"[OK] GEMINI_PROXY_BASE_URL = {settings.GEMINI_PROXY_BASE_URL}")
    print(f"[OK] API key set: {bool(settings.GEMINI_PROXY_API_KEY)}")
    if settings.GEMINI_PROXY_API_KEY:
        print(f"     Key preview: {settings.GEMINI_PROXY_API_KEY[:10]}...")
except Exception as e:
    print(f"[FAIL] Config error: {e}")
    sys.exit(1)

# Test 2: LLM service
print("\n=== [2/5] Test LLM service ===")
try:
    from app.services.llm_service import chat_completion, LLMError
    response = chat_completion(
        messages=[{"role": "user", "content": "Trả lời 1 từ: 2+2=?"}],
        temperature=0,
        max_tokens=20,
    )
    print(f"[OK] LLM response: {response['answer']}")
    print(f"     Tokens: {response['usage']}")
except LLMError as e:
    print(f"[FAIL] LLM error: {e}")
    print("  → Check API key, proxy URL, network")
except Exception as e:
    print(f"[FAIL] Unexpected: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Intent router
print("\n=== [3/5] Test intent router ===")
try:
    from app.services.intent_router import classify_intent
    result = classify_intent("Tìm quiz về động vật")
    print(f"[OK] Intent: {result.intent}")
    print(f"     Confidence: {result.confidence}")
    print(f"     Reasoning: {result.reasoning}")
    if result.semantic:
        print(f"     Semantic: {result.semantic.query}")
except Exception as e:
    print(f"[FAIL] Router error: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Search service
print("\n=== [4/5] Test search service ===")
try:
    from app.services.search_service import search_quizzes
    hits = search_quizzes("động vật", top_k=3)
    print(f"[OK] Found {len(hits)} hits")
    for h in hits[:3]:
        print(f"     - {h.get('id')}: score={h.get('score'):.3f}")
        payload = h.get("payload", {})
        print(f"       title: {payload.get('title', 'N/A')[:60]}")
except Exception as e:
    print(f"[FAIL] Search error: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Full orchestrator
print("\n=== [5/5] Test full orchestrator ===")
try:
    from app.db.session import SessionLocal
    from app.services.ai_orchestrator import run_ai_orchestrator
    from uuid import UUID

    db = SessionLocal()
    try:
        from app.models.user_auth.users import User
        from app.models.social.conversations import Conversation
        from app.models.social.conversation_members import ConversationMember
        from app.models.social.messages import Message

        # Ưu tiên dùng user_id/conv_id từ CLI, fallback về .first()
        if args.user_id and args.conv_id:
            print(f"[init] Using provided IDs from CLI")
            user = db.query(User).filter(User.id == UUID(args.user_id)).first()
            conv = db.query(Conversation).filter(Conversation.id == UUID(args.conv_id)).first()
            if not user:
                print(f"[FAIL] User {args.user_id} not found")
                sys.exit(1)
            if not conv:
                print(f"[FAIL] Conversation {args.conv_id} not found")
                sys.exit(1)
        else:
            print(f"[init] No --user-id/--conv-id provided, auto-pick first")
            user = db.query(User).first()
            conv = (
                db.query(Conversation)
                .join(ConversationMember)
                .filter(ConversationMember.user_id == user.id)
                .first()
            )

        if not user or not conv:
            print("[SKIP] No user/conversation in DB, skip orchestrator test")
        else:
            # Verify user is a member of the conversation
            member = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conv.id,
                ConversationMember.user_id == user.id,
            ).first()
            if not member:
                print(f"[WARN] User {user.id} is not a member of conv {conv.id}")
                print(f"       Orchestrator may fail membership check")

            # ----------------------------------------------------------------
            # Insert 1 user_message THẬT vào DB trước khi gọi orchestrator.
            # Lý do: ai_runs.user_message_id có FK -> messages.id.
            # Nếu dùng UUID giả sẽ vi phạm FK constraint.
            # ----------------------------------------------------------------
            user_text = args.text
            user_msg = Message(
                conversation_id=conv.id,
                sender_id=user.id,
                sender_type="user",
                content=user_text,
            )
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)
            print(f"[init] Inserted user_message: id={user_msg.id}")
            print(f"[init] conv_id={conv.id}, user_id={user.id}")

            result = run_ai_orchestrator(
                db=db,
                conversation_id=conv.id,
                user_id=user.id,
                user_message=user_text,
                user_message_id=user_msg.id,
            )
            print(f"[OK] Answer: {result['answer'][:200]}")
            print(f"     Intent: {result['intent']}")
            print(f"     Confidence: {result['confidence']}")
            print(f"     Timings: {result.get('timings')}")
            print(f"     AI message id: {result.get('ai_message_id')}")
            if result.get("error"):
                print(f"     Error: {result['error']}")
    finally:
        db.close()
except Exception as e:
    print(f"[FAIL] Orchestrator error: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Done ===")
