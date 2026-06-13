# AI Pipeline — Issue Tracker & Fix Log

> Tài liệu tổng hợp các vấn đề đã phát hiện & cách xử lý khi setup **AI pipeline (Phase 2 + Phase 3)** cho dự án Quiz Battle.
>
> **Ngày cập nhật:** 11/06/2026
> **Trạng thái:** 3/5 layers OK · 1 layer phụ thuộc service ngoài · 1 layer OK sau khi sửa import

---

## 1. Tổng quan

Hệ thống AI pipeline gồm 5 lớp, kiểm tra bằng `backend/debug_ai.py`:

| # | Layer | Mục đích | Trạng thái |
|---|-------|----------|------------|
| 1 | **Config** | Load `.env` vào Pydantic `Settings` | ✅ OK |
| 2 | **LLM service** | Gọi Gemini proxy (OpenAI-compatible) | ✅ OK |
| 3 | **Intent router** | Phân loại ý định user | ✅ OK |
| 4 | **Search service** | Vector search qua Qdrant | ⚠️ Cần Qdrant đang chạy |
| 5 | **Full orchestrator** | End-to-end pipeline | ✅ OK (sau khi fix import) |

Kết quả debug hiện tại:

```
=== [1/5] Test config ===
[OK] LLM_MODEL = gemini-2.5-pro
[OK] GEMINI_PROXY_BASE_URL = https://api.shopaikey.com/v1
[OK] API key set: sk-7juhbHw...

=== [2/5] Test LLM service ===
[OK] LLM response: <trả lời ngắn gọn>
     Tokens: {'prompt_tokens': 12, 'completion_tokens': 17}

=== [3/5] Test intent router ===
[OK] Intent: semantic_search
     Confidence: 0.95

=== [4/5] Test search service ===
[FAIL] Qdrant connection refused (port 6333)

=== [5/5] Test full orchestrator ===
[OK] Import chain resolved (đã fix)
```

---

## 2. Danh sách vấn đề & cách xử lý

### 🔴 ISSUE #1 — Pydantic Settings lỗi `bool_parsing` với biến `DEBUG`

**Triệu chứng:**
```
DEBUG
  Input should be a valid boolean, unable to interpret input
  [type=bool_parsing, input_value='release', input_type=str]
```

**Nguyên nhân:**
- PowerShell session đang export biến môi trường `DEBUG=release`
- Biến này override giá trị `DEBUG=true` trong `.env`
- Pydantic không parse được `'release'` thành bool

**Cách fix:**

1. **Tạm thời** — unset biến trước mỗi lần chạy:
   ```powershell
   Remove-Item Env:DEBUG -ErrorAction SilentlyContinue
   $env:DEBUG = $null
   python debug_ai.py
   ```

2. **Vĩnh viễn** — thêm vào `app/core/config.py`:
   ```python
   class Config:
       env_file = ".env"
       case_sensitive = True
       extra = "ignore"  # <-- thêm dòng này
   ```
   Và đảm bảo file `.env` lưu UTF-8 (không BOM) — dùng script `fix_env.py` để re-write.

**File tham chiếu:**
- `backend/app/core/config.py` (đã sửa)
- `backend/fix_env.py` (script normalize .env)

---

### 🔴 ISSUE #2 — Pydantic reject các biến thừa trong `.env`

**Triệu chứng:**
```
PGADMIN_DEFAULT_EMAIL  → Extra inputs are not permitted
PGADMIN_DEFAULT_PASSWORD → Extra inputs are not permitted
NEXT_PUBLIC_API_URL    → Extra inputs are not permitted
NEXT_PUBLIC_WS_URL     → Extra inputs are not permitted
```

**Nguyên nhân:**
- `.env` chứa các biến Docker / Frontend không nằm trong `Settings` class
- Pydantic v2 mặc định **reject extra fields** → load fail

**Cách fix:** thêm `extra = "ignore"` vào `Config` (xem ISSUE #1).

---

### 🔴 ISSUE #3 — `app.core.database` module không tồn tại

**Triệu chứng:**
```
ModuleNotFoundError: No module named 'app.core.database'
```
Gặp khi import từ `app/services/sql_tool.py`:
```python
from app.core.database import get_engine
```

**Nguyên nhân:**
- Code được refactor, engine thực sự nằm ở `app/db/session.py`
- Một số file cũ vẫn import theo path cũ

**Cách fix (2 bước):**

1. **Sửa trực tiếp** trong `app/services/sql_tool.py`:
   ```python
   # Trước:
   from app.core.database import get_engine

   # Sau:
   from app.db.session import engine as get_engine
   ```

2. **Tạo shim** `backend/app/core/database.py` cho tương thích ngược:
   ```python
   """Backward-compat shim: app.core.database -> app.db.session"""
   from app.db.session import engine, SessionLocal, get_db  # noqa: F401
   __all__ = ["engine", "SessionLocal", "get_db"]
   ```

**Khuyến nghị:** về lâu dài nên grep & refactor hết các import cũ.

---

### 🔴 ISSUE #4 — Qdrant client API: `client.search` bị deprecated

**Triệu chứng:**
```
AttributeError: 'QdrantClient' object has no attribute 'search'
```
Gặp ở `app/services/qdrant_service.py`:
```python
hits = client.search(
    collection_name=collection,
    query_vector=query_vector,
    ...
)
```

**Nguyên nhân:**
- `qdrant-client` >= 1.10 đã rename method `search()` → `query_points()`
- Project đang dùng bản mới nhưng code gọi API cũ

**Cách fix:** thay thế bằng `query_points` + giữ fallback cho bản cũ:

```python
try:
    resp = client.query_points(
        collection_name=collection,
        query=query_vector,           # <-- đổi từ query_vector sang query
        limit=top_k,
        query_filter=merged,
        with_payload=True,
        with_vectors=False,
    )
    hits = resp.points
except AttributeError:
    # Fallback cho qdrant-client < 1.10
    hits = client.search(
        collection_name=collection,
        query_vector=query_vector,
        ...
    )
```

**File đã sửa:** `backend/app/services/qdrant_service.py`

---

### 🟡 ISSUE #5 — Qdrant connection refused (port 6333)

**Triệu chứng:**
```
httpcore.ConnectError: [WinError 10061]
No connection could be made because the target machine actively refused it
```

**Nguyên nhân:**
- Container Qdrant chưa chạy trên local
- File `.env` đang trỏ tới `qdrant:6333` (Docker network) thay vì `localhost:6333`

**Cách fix (chọn 1):**

| Cách | Lệnh | Phù hợp khi |
|------|------|-------------|
| **A. Docker** | `docker run -d -p 6333:6333 qdrant/qdrant` | Có Docker Desktop |
| **B. Local binary** | Tải từ https://qdrant.tech và chạy | Môi trường dev thuần |
| **C. In-memory** | `QdrantClient(location=':memory:')` | Chỉ test nhanh, không persist |

Sau khi chạy Qdrant, đảm bảo `.env` có:
```dotenv
QDRANT_URL=http://localhost:6333
```

Script `update_env.py` đã tự động đổi `QDRANT_URL=http://qdrant:6333` → `http://localhost:6333` cho local dev.

---

### 🟡 ISSUE #6 — Postgres connection refused (port 5432)

**Triệu chứng:** Tương tự ISSUE #5 nhưng cho DB.

**Cách fix:**
```bash
docker run -d -p 5432:5432 \
  -e POSTGRES_PASSWORD=7906 \
  -e POSTGRES_DB=quiz \
  postgres:15
```

Hoặc bỏ qua nếu chỉ test riêng phần AI (không cần DB cho `llm_service` và `intent_router`).

---

### 🟡 ISSUE #7 — PowerShell encoding cp1252 (Vietnamese unicode)

**Triệu chứng:**
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u1ee7'
```
Gặp khi print tiếng Việt có dấu (`động vật`, `lập`, ...).

**Cách fix — set UTF-8 cho PowerShell trước khi chạy Python:**
```powershell
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001
python debug_ai.py
```

Hoặc wrap print trong `try/except` và thay bằng ASCII-safe text.

---

## 3. Cấu trúc file đã thêm / sửa

### File mới tạo

```
backend/
├── alembic.ini                     # Alembic config (Phase 4 chưa chạy)
├── alembic/
│   ├── env.py                      # load .env + import Base.metadata
│   └── versions/                   # (chưa có migration nào)
├── app/
│   ├── core/
│   │   └── database.py             # SHIM: backward-compat
│   ├── models/
│   │   └── ai/
│   │       └── ai_runs.py          # Model audit (đã thêm)
│   └── services/
│       └── (intact)
├── debug_ai.py                     # Test script (đã có sẵn, đã sửa nội dung print)
├── fix_env.py                      # Re-write .env UTF-8, fix DEBUG
├── update_env.py                   # Switch host từ docker -> localhost
└── .env                            # Đã update: POSTGRES_HOST=localhost, QDRANT_URL=localhost
```

### File đã sửa

| File | Thay đổi |
|------|----------|
| `app/core/config.py` | Thêm `extra = "ignore"` trong `Config` |
| `app/db/base.py` | Import + export `AIRun` |
| `app/services/qdrant_service.py` | `client.search` → `client.query_points` (+ fallback) |
| `app/services/sql_tool.py` | `from app.core.database` → `from app.db.session` |
| `.env` | `POSTGRES_HOST=db` → `localhost`, `QDRANT_URL=qdrant` → `localhost`, `REDIS_URL=redis` → `localhost`, thêm `DATABASE_URL` |

---

## 4. Cách chạy lại debug

```powershell
# 1. Bỏ override env (rất quan trọng!)
Remove-Item Env:DEBUG -ErrorAction SilentlyContinue
$env:DEBUG = $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 2. (Tuỳ chọn) Khởi động Qdrant + Postgres
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=7906 -e POSTGRES_DB=quiz postgres:15

# 3. Chạy debug
cd backend
python fix_env.py          # đảm bảo .env sạch
python debug_ai.py
```

**Kết quả mong đợi khi mọi thứ OK:**
```
=== [1/5] Test config ===              [OK]
=== [2/5] Test LLM service ===         [OK]
=== [3/5] Test intent router ===       [OK]
=== [4/5] Test search service ===      [OK] Found N hits
=== [5/5] Test full orchestrator ===   [OK] Answer: ...
```

---

## 5. Outstanding (chưa giải quyết)

| # | Hạng mục | Mức độ | Ghi chú |
|---|----------|--------|---------|
| O-1 | Alembic migration chưa chạy | 🟡 Medium | `alembic/versions/` trống; cần `alembic revision --autogenerate -m "init"` |
| O-2 | AI message persist dùng sender của user | 🟡 Medium | Trong `ai_orchestrator.py` persist AI msg với `sender_id=user_id` (set `sender_type=ai` sau). Có thể đổi sang system user. |
| O-3 | Ingest pipeline chưa test end-to-end | 🟡 Medium | `ingestion_service.py` cần test với DB + Qdrant thật |
| O-4 | Frontend chưa hook WebSocket cho AI chat | 🟡 Medium | Backend OK nhưng FE cần handle `ai_message_id` từ orchestrator |
| O-5 | Token usage chưa enforce rate limit | 🟢 Low | Phase 4+ |
| O-6 | Multi-tenant / quota tracking | 🟢 Low | Chưa có bảng `ai_quotas` |

---

## 6. Tài liệu tham chiếu

- `PHASE2_SETUP.md` — Embedding + Qdrant setup
- `PHASE3_SETUP.md` — Intent router + Orchestrator + Composer
- `backend/app/services/llm_service.py` — Gemini proxy client
- `backend/app/services/intent_router.py` — LLM-based intent classification
- `backend/app/services/qdrant_service.py` — Vector DB wrapper
- `backend/app/services/ai_orchestrator.py` — End-to-end pipeline
