# Plan: Fix REST API bị block khi `@ai` đang chạy

## 1. Tóm tắt vấn đề

**Triệu chứng (user report):**
- ✅ WebSocket chat + tag `@ai ...` hoạt động bình thường → AI trả lời OK
- ❌ Các REST API khác (POST/GET messages, conversations, friends, etc.) **bị block / treo / timeout** trong khi AI đang xử lý

**Nghi vấn chính:**
WebSocket handler `_maybe_trigger_ai` chạy AI orchestrator **đồng bộ** trong background task, chiếm giữ event loop hoặc connection pool DB → các request REST khác phải chờ.

---

## 2. Phân tích nguyên nhân gốc

### 2.1. AI orchestrator chạy **sync blocking** trong event loop

Trong `chat_socket.py` (dòng ~150):

```python
asyncio.create_task(
    _maybe_trigger_ai(...)
)
```

Và trong `_maybe_trigger_ai` (dòng ~260):

```python
result = run_ai_orchestrator(  # ← HÀM SYNC, CHẠY 5-30 GIÂY
    db=db, ...
)
```

`run_ai_orchestrator` là hàm sync gọi:
1. `classify_intent()` → HTTP request tới Gemini proxy (~300-800ms)
2. `_execute_tools()` → query Qdrant / SQL (~50-200ms)
3. `_compose_answer()` → HTTP request tới Gemini proxy lần 2 (~500-3000ms với Pro)
4. Persist message + audit row (~20-50ms)

**Tổng: 1-4 giây** (có thể tới 10s+ nếu proxy chậm hoặc Pro model).

### 2.2. Code đã có `asyncio.to_thread` wrapper NHƯNG KHÔNG DÙNG

Trong `ai_orchestrator.py` đã có:

```python
async def run_ai_orchestrator_async(...):
    return await asyncio.to_thread(
        run_ai_orchestrator, ...
    )
```

**NHƯNG** trong `chat_socket.py` lại gọi thẳng `run_ai_orchestrator(...)` (sync) → block event loop toàn bộ FastAPI app.

### 2.3. DB session chia sẻ giữa sync code và async context

Trong `_maybe_trigger_ai`:

```python
db = SessionLocal()  # ← session tạo trong async function
try:
    ...
    result = run_ai_orchestrator(db=db, ...)  # ← sync, hold session 1-4s
    ...
finally:
    db.close()
```

Session DB được giữ suốt thời gian AI xử lý. Nếu connection pool giới hạn (mặc định SQLAlchemy 5 connections), mọi request REST khác phải **chờ session rảnh**.

### 2.4. Nhiều tab WebSocket + spam `@ai` → cạn kiệt pool

Mỗi user mở 1 tab chat = 1 WebSocket connection. Mỗi message `@ai` = 1 sync task giữ 1 DB session ~1-4s. Với 5-10 user chat đồng thời → connection pool cạn → REST API block.

---

## 3. Các nguyên nhân phụ (cần verify)

| # | Nghi vấn | Cách verify |
|---|----------|-------------|
| 1 | Event loop block vì sync code | Log thời gian `_maybe_trigger_ai`, so sánh với health check ping |
| 2 | DB connection pool cạn | Log `pool.status()` trước/sau AI call |
| 3 | Gemini proxy timeout dài | Test trực tiếp với curl, đo p95 latency |
| 4 | Circuit breaker mở oan | Check log `CircuitBreakerOpen` có xuất hiện liên tục không |
| 5 | HTTP client không có timeout riêng cho AI | Xem `httpx`/`requests` config trong `llm_service.py` |

---

## 4. Plan giải quyết (theo thứ tự ưu tiên)

### ƯU TIÊN 1 — Dùng async wrapper để không block event loop

**File:** `backend/app/websockets/chat_socket.py`

Đổi từ:

```python
asyncio.create_task(
    _maybe_trigger_ai(...)
)
```

Thành:

```python
asyncio.create_task(
    _maybe_trigger_ai_async(...)  # wrapper mới dùng run_ai_orchestrator_async
)
```

Trong `_maybe_trigger_ai`, đổi:

```python
from app.services.ai_orchestrator import run_ai_orchestrator

result = run_ai_orchestrator(
    db=db, ...  # ← giữ session hiện tại
)
```

Thành 1 trong 2 cách:

**Cách A (đơn giản nhất):** Mỗi step orchestrator tự tạo session riêng.

```python
from app.services.ai_orchestrator import run_ai_orchestrator_async

result = await run_ai_orchestrator_async(
    db=None,  # ← orchestrator tự tạo SessionLocal() bên trong
    conversation_id=conversation_id,
    user_id=user_id,
    user_message=query,
    user_message_id=user_message_id,
    recent_history=history,
)
```

**Cách B (giữ session cũ):** Bọc trong `asyncio.to_thread`:

```python
result = await asyncio.to_thread(
    run_ai_orchestrator,
    db=db, ...
)
```

**Khuyến nghị: Cách A** — orchestrator quản lý session lifecycle, sạch sẽ hơn.

### ƯU TIÊN 2 — Tăng DB connection pool

**File:** `backend/app/db/session.py` (hoặc tương tự)

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=20,        # mặc định 5 → tăng lên 20
    max_overflow=10,     # cho phép burst thêm 10
    pool_timeout=10,     # timeout khi chờ connection (giây)
    pool_pre_ping=True,  # kiểm tra connection còn sống không
)
```

Nếu dùng async SQLAlchemy, set `pool_size=20` trong `create_async_engine`.

### ƯU TIÊN 3 — Tách DB session cho AI sang connection riêng

Trong `ai_orchestrator.py`, thay vì dùng `db` param, cho phép tự tạo session:

```python
def run_ai_orchestrator(
    db: Session | None = None,  # ← nếu None thì tự tạo
    ...
):
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        # ... existing code ...
    finally:
        if own_session:
            db.close()
```

### ƯU TIÊN 4 — Thêm timeout cho AI task

**File:** `backend/app/websockets/chat_socket.py`

```python
async def _maybe_trigger_ai_with_timeout(...):
    try:
        await asyncio.wait_for(
            _maybe_trigger_ai(...),
            timeout=15.0,  # 15s max
        )
    except asyncio.TimeoutError:
        logger.error(f"AI trigger timeout: conversation={conversation_id}")
        # Broadcast error message cho user
        await manager.broadcast(...)
```

### ƯU TIÊN 5 — Log để verify root cause

Thêm log chi tiết ở `_maybe_trigger_ai`:

```python
import time
t0 = time.time()
logger.info(f"AI task started: conversation={conversation_id}")
...
elapsed = (time.time() - t0) * 1000
logger.info(f"AI task done: {elapsed}ms, intent={result.get('intent')}")
```

Sau khi restart backend, send 1 message `@ai ...` rồi **ngay lập tức** gọi REST API `GET /api/v1/conversations`:
- Nếu REST trả về trong <500ms → root cause không phải block event loop
- Nếu REST trả về >2s hoặc timeout → block event loop là root cause → ưu tiên 1 chưa fix

### ƯU TIÊN 6 (optional) — Tách AI orchestrator sang process riêng

Nếu scale lớn, dùng **Celery / RQ / Arq** để chạy AI task trong worker process riêng:

```python
# celery task
@celery_app.task(bind=True, max_retries=2)
def run_ai_orchestrator_task(self, ...):
    return run_ai_orchestrator(...)
```

WebSocket chỉ cần:

```python
run_ai_orchestrator_task.delay(...)
```

Worker pick up task, xử lý, push kết quả qua Redis Pub/Sub → WebSocket broadcast.

**Khuyến nghị: làm ưu tiên 1-4 trước, ưu tiên 6 chỉ khi cần scale.**

---

## 5. Kế hoạch triển khai (thứ tự)

| Bước | File | Nội dung | Effort |
|------|------|----------|--------|
| 1 | `chat_socket.py` | Đổi `run_ai_orchestrator` → `run_ai_orchestrator_async` (Cách A) | 10 phút |
| 2 | `ai_orchestrator.py` | Hỗ trợ `db=None` → tự tạo session | 5 phút |
| 3 | `db/session.py` | Tăng `pool_size=20`, `max_overflow=10` | 5 phút |
| 4 | `chat_socket.py` | Thêm timeout 15s cho AI task | 5 phút |
| 5 | `chat_socket.py` | Thêm log timing chi tiết | 5 phút |
| 6 | - | Restart backend, test lại | 10 phút |
| 7 | - | Nếu vẫn lỗi → check log Gemini proxy latency, circuit breaker | 15 phút |

**Tổng effort ước tính: ~1 giờ** (chưa tính debug phát sinh).

---

## 6. Test plan sau khi fix

### Test 1: REST API không block khi AI chạy
1. Mở 2 tab: tab A = chat, tab B = bất kỳ page gọi REST (vd: danh sách conversations)
2. Tab A gửi `@ai tìm quiz về lịch sử Việt Nam`
3. **Ngay lập tức** (trong vòng 1s) refresh tab B
4. **Expected:** tab B load bình thường, không treo

### Test 2: AI vẫn trả lời đúng
1. Gửi `@ai top 5 quiz có nhiều câu hỏi nhất`
2. **Expected:** nhận AI reply trong <5s, nội dung đúng

### Test 3: Spam `@ai` không crash
1. Gửi 10 message `@ai ...` liên tiếp trong 5s
2. **Expected:** 10 AI reply trả về đầy đủ, không có message nào bị drop, REST API vẫn hoạt động

### Test 4: Connection pool không cạn
```python
# Test thủ công
from app.db.session import engine
print(engine.pool.status())
```
Sau khi 10 AI task chạy, check `pool.checkedout()` không vượt `pool_size + max_overflow`.

---

## 7. Rollback plan

Nếu fix gây lỗi mới, revert theo thứ tự ngược:
1. Tắt `AI_CHAT_ENABLED = False` trong `chat_socket.py` → AI ngừng hoạt động, REST OK
2. Revert các thay đổi ở `ai_orchestrator.py` và `db/session.py`
3. Restart backend

---

## 8. Đề xuất thứ tự làm

Nếu bạn duyệt plan này, tôi sẽ triển khai theo thứ tự:

1. **Bước 1+2** (chuyển sang async + tự tạo session) — fix root cause chính
2. **Bước 3** (tăng pool) — phòng case spike traffic
3. **Bước 4+5** (timeout + log) — safety net
4. **Test lại theo test plan mục 6**

Bạn ok với plan này không? Nếu có hướng khác (vd: muốn làm ưu tiên 6 Celery ngay) thì tôi điều chỉnh.
