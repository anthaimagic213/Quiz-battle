# NEXT_STEPS.md — Sau khi Debug AI Pipeline pass hết 5/5

> Status: Phase 3 (AI Pipeline) ✅ DONE
> Generated: 2026-06-11
> Trigger: `python debug_ai.py` chạy thành công end-to-end

---

## 0. Trạng thái hiện tại (snapshot)

```
[1/5] Config            ✅ OK   LLM_MODEL + API key hợp lệ
[2/5] LLM service       ✅ OK   Gemini proxy trả lời đúng
[3/5] Intent router     ✅ OK   Phân loại semantic_search, confidence=0.95
[4/5] Search service    ✅ OK   Qdrant trả 1 hit (Quiz mèo, score=0.644)
[5/5] Orchestrator      ✅ OK   End-to-end:
                              - Insert user_message thật (FK ok)
                              - Router → tool → composer
                              - Persist AI message
                              - Write ai_runs audit
                              - Total ~9s
```

**Đã fix trong session này:**

| # | Lỗi | File | Fix |
|---|------|------|-----|
| 1 | `query_points` API mismatch | `qdrant_service.py` | Đổi sang client mới (đã có từ trước) |
| 2 | `ImportError: fastapi` | `search_service.py` | Cài `fastapi` vào container |
| 3 | `ImportError: psycopg2` | `app/db/session.py` | Cài `psycopg2-binary` |
| 4 | `InvalidRequestError: RefreshToken` | `app/db/base.py` | Thêm import `KickedPlayer` |
| 5 | `FK violation ai_runs.user_message_id` | `debug_ai.py` | Insert `Message` thật thay vì UUID giả |
| 6 | Debug script không có CLI args | `debug_ai.py` | Thêm `--user-id`/`--conv-id`/`--text` |

---

## 1. Đề xuất thứ tự ưu tiên

### 🔴 P0 — Làm ngay hôm nay (≤ 1h tổng)

#### 1.1. Cập nhật documentation

- [ ] **Update `AI_PIPELINE_ISSUES.md`**
  - Đánh dấu 5/5 layer = RESOLVED
  - Ghi lại 6 fix đã apply ở trên
  - Thêm section "How to test" với command chạy `debug_ai.py`
  - Effort: **5 phút**

- [ ] **Update `PHASE2_SETUP.md`**
  - Đổi status Phase 3 từ `TODO` → `DONE`
  - Effort: **5 phút**

- [ ] **Tạo file này (`NEXT_STEPS.md`)** ✅
  - Effort: **đã xong**

#### 1.2. Production hygiene

- [ ] **Alembic migration setup** (chưa có)
  - Hiện tại schema dùng `Base.metadata.create_all()` trong `app/main.py`
  - Khi deploy lần 2: không có cách track schema drift
  - Cần: init `alembic`, tạo initial migration từ models hiện tại
  - Effort: **30 phút**
  - Lý do P0: bất kỳ thay đổi column nào (vd thêm `metadata` vào `Message`) sẽ cần migration thủ công

---

### 🟡 P1 — Tuần này (nếu có thời gian)

#### 1.3. Refactor code (technical debt)

- [ ] **Refactor `app/services/message_service.py`**
  - Tách `HTTPException` (FastAPI) ra khỏi service layer
  - Service nên raise domain exception (`MessageNotFound`, `NotConversationMember`) thuần tuý
  - Router sẽ catch và convert thành HTTPException
  - Lý do: hiện tại không unit-test được service nếu không có FastAPI context
  - Effort: **15 phút**

- [ ] **Refactor `app/db/session.py` thành lazy engine**
  - Engine hiện tại tạo ở module-level → crash lúc import nếu thiếu driver
  - Có thể cải thiện: dùng `get_engine()` factory pattern + thread-safe lazy init
  - Lợi: test scripts, dry-run tools, multi-db đều dùng được
  - Effort: **15 phút**

#### 1.4. Test coverage

- [ ] **Unit tests cho `intent_router`**
  - Mock LLM response, assert routing decisions
  - Test 5 intent: semantic_search, text_to_sql, smalltalk, clarify, get_my_*
  - Effort: **30 phút**

- [ ] **Unit tests cho `ai_orchestrator`**
  - Mock LLM + mock Qdrant + in-memory SQLite
  - Verify: insert message → run orchestrator → audit row tồn tại
  - Effort: **45 phút**

- [ ] **E2E test: WebSocket AI flow**
  - Connect WS, gửi message, verify AI response broadcast
  - Effort: **30 phút**

---

### 🟢 P2 — Sau khi production stable

#### 1.5. Observability

- [ ] **Structured logging (JSON)**
  - Hiện tại: `logger.info(f"...")` dạng string
  - Nên: `logger.info("ai_pipeline_complete", extra={"intent": ..., "ms": ...})`
  - Tool: `structlog` hoặc `loguru`
  - Effort: **1h**

- [ ] **Prometheus metrics**
  - Counter: `ai_pipeline_runs_total{intent=...}`
  - Histogram: `ai_pipeline_duration_seconds`
  - Gauge: `ai_pipeline_in_flight`
  - Effort: **1h**

#### 1.6. Resilience

- [ ] **Circuit breaker cho LLM proxy**
  - Nếu Gemini proxy 503 liên tục → tự tắt route trong 30s
  - Tránh cascade failure
  - Tool: `pybreaker` hoặc custom
  - Effort: **1h**

- [ ] **Retry với exponential backoff cho audit write**
  - `_write_ai_run_audit` hiện best-effort, fail → log warning
  - Có thể push vào Redis queue + worker xử lý sau
  - Effort: **1h30**

#### 1.7. Phase 4 — Tính năng mới

- [ ] **Streaming response (Server-Sent Events)**
  - User gửi câu hỏi dài → stream từng chunk answer
  - Effort: **2h**

- [ ] **AI memory / context window management**
  - Hiện `recent_history` chỉ lấy 3 turns
  - Có thể thêm: tóm tắt context dài thành key facts
  - Effort: **3h**

- [ ] **Multi-user concurrent test**
  - Test 10 user cùng gửi message trong 1s
  - Verify không có race condition trong audit
  - Effort: **1h**

---

## 2. Quick wins (nếu bạn muốn 1 task nhỏ 15-30p)

| Task | Lý do | Effort |
|------|-------|--------|
| Thêm `--no-db` flag cho `debug_ai.py` | Test nhanh không cần DB | 15p |
| Thêm `Makefile` target `make debug-ai` | Tiện hơn nhớ command | 5p |
| In số `tokens used` ước tính theo ngày | Theo dõi cost Gemini | 20p |
| Thêm pre-commit hook (`ruff check`) | Tránh import lỗi typo | 15p |

---

## 3. Không nên làm (out of scope)

- ❌ Chuyển từ FastAPI sang framework khác — đang ổn
- ❌ Viết lại LLM service từ đầu — chỉ cần thêm streaming
- ❌ Build custom vector DB — Qdrant đủ dùng
- ❌ Deploy production trước khi có Alembic — sẽ regret
- ❌ Thêm nhiều intent nữa — 7 intent hiện tại đủ cho MVP

---

## 4. Decision points cần bạn confirm

1. **Alembic vs DBSchema-as-code?**
   - Alembic (chuẩn SQLAlchemy) hay tự quản `.sql` files?
   - Recommendation: **Alembic**

2. **Có muốn viết test từ đầu hay tăng dần?**
   - TDD ngay từ feature mới, hay chỉ test bug vừa fix?
   - Recommendation: **Tăng dần** (viết test cho orchestrator đầu tiên)

3. **Production deploy target?**
   - Railway / Render / VPS / Docker trên server riêng?
   - Ảnh hưởng đến CI/CD setup

4. **Có muốn caching layer (Redis) cho Qdrant queries?**
   - Lợi: giảm latency, giảm Qdrant load
   - Hại: data stale nếu ingest xong nhưng cache chưa expire
   - Recommendation: **Có, TTL=60s cho query phổ biến**

---

## 5. Recommended next action

> **Làm P0 ngay (1h):**
> 1. Update `AI_PIPELINE_ISSUES.md` (5p)
> 2. Update `PHASE2_SETUP.md` (5p)
> 3. Setup Alembic (30p)
> 4. Quick commit + push
>
> Sau đó quyết định P1 (refactor vs test first).
