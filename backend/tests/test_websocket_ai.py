"""
Test WebSocket chat client với AI.
Chạy: python tests/test_websocket_ai.py
"""

import asyncio
import json
import sys
import os

# Mock settings trước
sys.path.insert(0, os.path.abspath('.'))

import websockets
import httpx
from uuid import UUID


async def get_auth_token(email: str, password: str, base_url: str = "http://localhost:8000") -> str:
    """
    Login và lấy access token.
    Adjust endpoint theo API thật của bạn.
    """
    async with httpx.AsyncClient() as client:
        # Giả sử endpoint login là POST /api/v1/auth/login
        # Điều chỉnh theo codebase thật
        response = await client.post(
            f"{base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("access_token") or data.get("token")


async def get_or_create_conversation(user1_id: str, user2_id: str, token: str, base_url: str = "http://localhost:8000") -> str:
    """
    Tạo hoặc lấy conversation giữa 2 users.
    Trả về conversation_id.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        # Endpoint tạo conversation
        response = await client.post(
            f"{base_url}/api/v1/conversations",
            headers=headers,
            json={
                "type": "direct",
                "member_ids": [user2_id],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["id"]


async def test_websocket_ai():
    """Test gửi @ai message và nhận AI reply."""

    # === Config ===
    BASE_URL = "http://localhost:8000"
    WS_URL = "ws://localhost:8000"
    TEST_EMAIL = "test@example.com"  # TODO: đổi thành user thật
    TEST_PASSWORD = "testpassword"   # TODO: đổi thành pass thật
    TEST_USER2_ID = "00000000-0000-0000-0000-000000000000"  # TODO: UUID user khác

    print("=== Test WebSocket AI ===\n")

    # 1. Login
    print("[1/4] Logging in...")
    try:
        token = await get_auth_token(TEST_EMAIL, TEST_PASSWORD, BASE_URL)
        print(f"[OK] Got token: {token[:20]}...")
    except Exception as e:
        print(f"[FAIL] Login failed: {e}")
        print("  → Make sure backend is running and user exists")
        return

    # 2. Get user_id from token (decode JWT)
    # TODO: decode JWT properly
    user_id = TEST_USER2_ID  # placeholder
    print(f"[OK] User ID: {user_id}")

    # 3. Get/create conversation
    print("\n[2/4] Getting conversation...")
    try:
        conv_id = await get_or_create_conversation(user_id, TEST_USER2_ID, token, BASE_URL)
        print(f"[OK] Conversation ID: {conv_id}")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        return

    # 4. Connect WebSocket
    print(f"\n[3/4] Connecting WebSocket: {WS_URL}/ws/chat/{conv_id}")
    ws_url = f"{WS_URL}/ws/chat/{conv_id}?token={token}"

    try:
        async with websockets.connect(ws_url) as websocket:
            print("[OK] Connected")

            # 5. Send @ai message
            print("\n[4/4] Sending @ai message...")
            ai_query = "@ai tìm quiz về động vật"
            await websocket.send(json.dumps({
                "type": "SEND_MESSAGE",
                "data": {"content": ai_query},
            }))
            print(f"[OK] Sent: {ai_query}")

            # 6. Listen for responses (expect 2: user msg + AI reply)
            print("\n--- Listening for responses (timeout 10s) ---")
            responses = []
            try:
                for _ in range(5):  # max 5 messages
                    response = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=10.0,
                    )
                    data = json.loads(response)
                    responses.append(data)

                    if data.get("type") == "CHAT_MESSAGE":
                        msg = data.get("data", {})
                        sender_type = msg.get("sender_type")
                        content = msg.get("content", "")
                        print(f"  [{sender_type}] {content[:100]}")

                        if sender_type == "ai":
                            print("\n[OK] Got AI reply!")
                            break
            except asyncio.TimeoutError:
                print("\n[FAIL] Timeout waiting for AI reply")

            # Summary
            print(f"\n=== Summary ===")
            print(f"Total messages received: {len(responses)}")
            user_msgs = [r for r in responses if r.get("data", {}).get("sender_type") == "user"]
            ai_msgs = [r for r in responses if r.get("data", {}).get("sender_type") == "ai"]
            print(f"User messages: {len(user_msgs)}")
            print(f"AI messages: {len(ai_msgs)}")

            if ai_msgs:
                print(f"\n[OK] TEST PASSED — AI reply received")
            else:
                print(f"\n[FAIL] No AI reply")

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"[FAIL] WebSocket connection failed: {e}")
        print("  → Check token, conversation_id, and membership")
    except Exception as e:
        print(f"[FAIL] Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_websocket_ai())
