# Phase 2: RAG Foundation (Qdrant + Embedding) - Setup Guide

> **Trạng thái hiện tại: ✅ DONE** (đã migrate sang Gemini proxy + ingest chat message).
> Tài liệu này mô tả hệ thống Phase 2 đang chạy thật trong repo này, không phải kế hoạch.

## Overview

Phase 2 implements the RAG (Retrieval Augmented Generation) foundation on top of the social chat from Phase 1:

- Vector storage (Qdrant) + embedding pipeline (Gemini qua proxy).
- Hook ingestion tự động cho quiz, question và chat message.
- 3 search endpoint: quizzes / questions / messages (trong 1 conversation).
- **Chưa có** LLM orchestration, intent router, text-to-SQL — đó là Phase 3 (xem `PHASE3_SETUP.md`).

**Qdrant Collections (4, dim=3072, distance=Cosine):**

- [x] `quiz_embeddings` — 1 point / quiz (whole-quiz semantic search)
- [x] `question_embeddings` — 1 point / question (granular content search)
- [x] `retrieval_chunks` — reserved cho long content (hiện đang rỗng)
- [x] `chat_context_embeddings` — **đã populate** qua `ingest_message()` (chat RAG cho Phase 3+)

**Embedding Pipeline:**

- [x] `services/qdrant_service.py` — Qdrant client + collection bootstrap + 2 loại filter (`public_filter`, `chat_filter`)
- [x] `services/embedding_service.py` — gọi Gemini proxy `/embeddings`, text builders
- [x] `services/ingestion_service.py` — upsert/remove vectors cho quiz, question, message; backfill idempotent
- [x] `services/search_service.py` — top-k semantic search (3 collection)
- [x] `services/llm_service.py` — gọi Gemini proxy `/chat/completions` (chuẩn bị cho Phase 3)

**API Endpoints:**

- [x] `GET /api/v1/search/quizzes?q=...&top_k=...`
- [x] `GET /api/v1/search/questions?q=...&top_k=...`
- [x] `GET /api/v1/conversations/{id}/messages/search?q=...&top_k=...` (mới)

**Hooks (tự động ingest, best-effort):**

- [x] `quiz_service.create_quiz_with_questions` — ingest quiz + questions
- [x] `quiz_service.update_quiz_with_questions` — re-ingest
- [x] `quiz_service.delete_quiz` — soft-delete → re-ingest (point sẽ bị dọn vì `is_deleted=true`); hard-delete → remove
- [x] `message_service.create_message` (REST) — ingest message
- [x] `message_service.update_message` (REST) — re-ingest
- [x] `message_service.delete_message` (REST) — soft-delete → dọn khỏi index
- [x] `chat_socket._handle_chat_send` (WebSocket) — ingest realtime

**Backfill:**

- [x] `scripts/backfill_embeddings.py` — reindex quiz + question public
- [x] `ingestion_service.reingest_all_messages()` — reindex message (bỏ soft-deleted)

## Structure: Separation of Concerns

```
Quiz / Question / Message CRUD
  ↓
Endpoint (Route Handler) / WebSocket
  ↓
Service (Business Logic + Ingestion Hook)
  ↓
ingestion_service → embedding_service → qdrant_service
  ↓                   ↓                     ↓
PostgreSQL         Gemini proxy          Qdrant
(source of truth)  (httpx, no GPU)       (vector store)

Search Request
  ↓
Endpoint (Route Handler)
  ↓
search_service → embedding_service → qdrant_service
  ↓                                     ↓
                                  Qdrant search
                                  (top-k, filter theo collection)
```

**Layered (mỗi layer độc lập, dễ mock):**

- **Routes / WebSocket**: HTTP / WS concern, auth.
- **Services**: business logic, gọi `ingest_*()` best-effort (lỗi Qdrant/embed chỉ log warning, không phá luồng chính).
- **embedding_service**: thin wrapper quanh Gemini proxy, swappable.
- **qdrant_service**: client + collection schema + 2 filter (`public_filter` cho quiz/question, `chat_filter` cho message).
- **ingestion_service**: chỗ duy nhất biết PostgreSQL → Qdrant mapping.
- **PostgreSQL vẫn là source of truth**; Qdrant là derived cache.

## Setup Steps

### 1. Pull dependencies

```bash
cd backend
pip install -r requirements.txt
```

Package chính (pinned để tránh drift API):

- `qdrant-client==1.9.0` — pin vì 1.10+ thay đổi signature `create_payload_index`.
- `httpx` — đã có sẵn, dùng gọi Gemini proxy.
- `pydantic-settings` — load `.env`.

### 2. Cấu hình `.env` (ở root, copy từ `env-docker-template.txt`)

```bash
cp env-docker-template.txt .env
# Sửa GEMINI_PROXY_API_KEY=sk-...
# Sửa SECRET_KEY=<random>
```

Các biến liên quan (xem `env-docker-template.txt` để biết thêm):

```ini
GEMINI_PROXY_BASE_URL=https://api.shopaikey.com/v1
GEMINI_PROXY_API_KEY=sk-...
LLM_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=3072
QDRANT_VECTOR_SIZE=3072
QDRANT_DISTANCE=Cosine
```

### 3. Khởi động full stack

```bash
docker compose up -d --build
```

Backend khi start sẽ:

1. Tạo schema Postgres nếu thiếu (`create_all()` fallback khi không có Alembic).
2. Gọi `ensure_collections()` — tạo 4 collection Qdrant nếu chưa có (idempotent), kèm payload indexes.
3. Health-check Gemini proxy (log warning nếu thiếu key, không fail boot).

Log mong đợi:

```
✅ Database tables created successfully!
✅ Qdrant collections ready!
✅ Gemini proxy API key configured.
INFO: Application startup complete.
```

### 4. Backfill (1 lần sau deploy đầu, hoặc sau khi đổi model/dim)

```bash
# Quiz + question public
docker exec quiz_battle_backend python -m scripts.backfill_embeddings

# (Tuỳ chọn) Message — bỏ soft-deleted
docker exec quiz_battle_backend python -c "
from app.db.session import SessionLocal
from app.services.ingestion_service import reingest_all_messages
db = SessionLocal()
try:
    n = reingest_all_messages(db, batch_size=100)
    print('reingested', n, 'messages')
finally:
    db.close()
"
```

Backfill idempotent (Qdrant upsert theo UUID nên chạy lại an toàn).

### 5. Test search endpoints

Swagger UI: `http://localhost:8000/docs`

```bash
# Quiz semantic search
GET /api/v1/search/quizzes?q=quiz+about+animals&top_k=5
Authorization: Bearer {token}

# Question semantic search
GET /api/v1/search/questions?q=biggest+animal+in+the+world&top_k=10
Authorization: Bearer {token}

# Message semantic search (trong 1 conversation, cần membership)
GET /api/v1/conversations/{conversation_id}/messages/search?q=con+m%C3%A8o&top_k=5
Authorization: Bearer {token}
```

### 6. Verify Qdrant (optional)

Qdrant dashboard: `http://localhost:6333/dashboard`

Hoặc nhanh từ container backend:

```bash
docker exec quiz_battle_backend python -c "
import urllib.request, json
data = json.loads(urllib.request.urlopen('http://qdrant:6333/collections').read())
for col in data.get('result',{}).get('collections',[]):
    info = json.loads(urllib.request.urlopen('http://qdrant:6333/collections/'+col['name']).read())
    cfg = info['result']['config']['params']['vectors']
    print(f\"{col['name']:30s} dim={cfg.get('size'):>5} points={info['result'].get('points_count', 0)}\")
"
```

## What's NOT Included Yet (chuyển sang Phase 3)

- ❌ LLM chat reply cho user (intent router + prompt assembly + tool calling).
- ❌ `ai_runs` audit table (lưu prompt, retrieval context, token usage).
- ❌ Text-to-SQL an toàn với whitelist table/column.
- ❌ Reranking layer (Phase 4).
- ❌ Caching kết quả retrieval (Phase 4).
- ❌ `retrieval_chunks` chưa populate (sẽ dùng cho long content ở Phase 4+).

## Next Steps (Phase 3 — xem `PHASE3_SETUP.md`)

1. Build intent router (semantic vs structured vs smalltalk).
2. Viết schema cho DB tables dùng cho LLM (whitelist table + column, kèm mô tả ngắn).
3. Xây safe text-to-SQL tool chỉ chấp nhận query do router emit (không cho LLM sinh SQL tự do).
4. Kết nối LLM (`gemini-2.5-flash` qua proxy) để compose answer.
5. Thêm bảng `ai_runs` để audit retrieval + prompt + token usage.
6. Reuse `chat_context_embeddings` để recall past message theo nghĩa (không phải theo thời gian).

## Collection Schema (đang chạy thật)

### `quiz_embeddings`

```
point.id         = str(quiz.id)
vector           = 3072-dim float[] (gemini-embedding-001)
payload:
  source_type    = "quiz"
  source_id      = str(quiz.id)
  quiz_id        = str(quiz.id)
  is_public      = bool
  is_deleted     = bool
  title          = str
  description    = str
  question_count = int
  created_at     = ISO datetime
  updated_at     = ISO datetime
```

### `question_embeddings`

```
point.id         = str(question.id)
vector           = 3072-dim float[]
payload:
  source_type    = "question"
  source_id      = str(question.id)
  quiz_id        = str(parent_quiz.id)
  is_public      = bool (inherited)
  is_deleted     = bool (inherited)
  content        = str
  question_type  = str
  quiz_title     = str
  created_at     = ISO datetime
  updated_at     = ISO datetime
```

### `retrieval_chunks` (reserved, hiện rỗng)

```
point.id         = uuid
vector           = 3072-dim float[]
payload:
  source_type    = "chunk"
  source_id      = str
  quiz_id        = str (optional)
  is_public      = bool
  is_deleted     = bool
  chunk_index    = int
  updated_at     = ISO datetime
```

### `chat_context_embeddings` (đã populate)

```
point.id         = str(message.id)
vector           = 3072-dim float[]
payload:
  source_type        = "chat_message"
  source_id          = str(message.id)
  quiz_id            = ""  (giữ schema đồng nhất)
  conversation_id    = str(message.conversation_id)
  sender_id          = str(message.sender_id)
  sender_type        = "user" | "ai" | "system"
  is_ai_generated    = bool
  is_deleted         = bool (theo Message.deleted_at)
  content            = str  (chỉ metadata; vector đã chứa semantic của content)
  created_at         = ISO datetime
  updated_at         = ISO datetime
```

## Payload Indexes (idempotent khi restart)

| Collection                | Field               | Type     | Ghi chú                              |
| ------------------------- | ------------------- | -------- | ------------------------------------ |
| all                       | `source_type`       | keyword  |                                      |
| all                       | `source_id`         | keyword  | dùng cho delete-by-source-id         |
| all                       | `quiz_id`           | keyword  | dùng cho delete-by-quiz-id           |
| all                       | `is_public`         | bool     |                                      |
| all                       | `is_deleted`        | bool     |                                      |
| all                       | `updated_at`        | datetime |                                      |
| `question_embeddings`     | `question_type`     | keyword  |                                      |
| `retrieval_chunks`        | `chunk_index`       | integer  |                                      |
| `chat_context_embeddings` | `conversation_id`   | keyword  | filter cho search message theo conv  |
| `chat_context_embeddings` | `sender_id`         | keyword  | lọc "tin nhắn của tôi" (Phase 3+)    |
| `chat_context_embeddings` | `is_ai_generated`   | bool     | lọc AI vs user (Phase 3+)            |

## Default Retrieval Filter

Có **2 filter** trong `qdrant_service.py`, áp theo collection:

| Collection                | Filter function | Điều kiện                              |
| ------------------------- | --------------- | -------------------------------------- |
| `quiz_embeddings`         | `public_filter` | `is_public=true AND is_deleted=false`  |
| `question_embeddings`     | `public_filter` | `is_public=true AND is_deleted=false`  |
| `chat_context_embeddings` | `chat_filter`   | `is_deleted=false`                     |
| `retrieval_chunks`        | `public_filter` | `is_public=true AND is_deleted=false`  |

`search_service` truyền `filter_type="public"` (mặc định) hoặc `filter_type="chat"` cho `qdrant_service.search()`.

Quyết định thiết kế: **chat message là dữ liệu riêng tư theo conversation**, không áp `is_public` (vì message không có field này). Khi search message, caller (endpoint) phải check membership trước khi gọi `search_messages()`.

## Authentication

- Tất cả endpoint search yêu cầu `Authorization: Bearer {token}`.
- Search quizzes/questions: dùng `current_user` từ JWT nhưng chưa dùng cho personalization (Phase 3+ sẽ dùng).
- Search messages: check user là member của `conversation_id` trước khi gọi `search_messages()`.

## Error Handling

- 400: query rỗng / `top_k` ngoài range.
- 401: thiếu / sai token.
- 403: không phải member conversation (search messages).
- 500: Qdrant / Gemini proxy lỗi.
- 503: Backend boot fail nếu Qdrant không reachable (intentional — không serve search khi vector index missing).

## Embedding Model

**Hiện tại:** `gemini-embedding-001` qua proxy `https://api.shopaikey.com/v1`

| Property            | Value                                                            |
| ------------------- | ---------------------------------------------------------------- |
| Vector size         | **3072** (mặc định model, đã chọn luôn để khỏi xung đột proxy)  |
| Distance            | Cosine                                                           |
| Max input length    | Tùy proxy (thường ~8K-36K tokens); backend giới hạn `EMBEDDING_MAX_CHARS=8000` |
| Language            | 100+ ngôn ngữ (rất tốt cho tiếng Việt + Anh)                    |
| Tốc độ              | ~200-500ms / call HTTP (cold start lần đầu); 50-200ms subsequent |
| Cần GPU?            | **Không**                                                        |
| Cần internet?       | **Có** (proxy bên thứ 3)                                        |
| E5 prefix?          | **Không** (Gemini embedding không cần `passage:` / `query:`)     |
| `output_dimensionality`? | **Không ép** — proxy OpenAI-compatible có thể bỏ qua field này, để Gemini trả default 3072 cho an toàn |

**Đã chọn 3072 thay vì ép 768/1536** vì:

- Proxy `api.shopaikey.com` là OpenAI-compatible, không đảm bảo tôn trọng `output_dimensionality` (Google native API mới hỗ trợ chuẩn).
- 768-dim vẫn quá nhỏ cho retrieval chất lượng cao; 3072 mặc định của model cho chất lượng tốt nhất.
- Đổi dim chỉ cần update 2 env + drop 4 collection + backfill (Qdrant lock dimension).

### Code hiện tại (đã migrate từ `sentence-transformers`)

```python
# app/services/embedding_service.py
def _post_embeddings(inputs, task_type, model=None):
    payload = {
        "model": model or settings.EMBEDDING_MODEL,
        "input": list(inputs),
        "task_type": task_type,   # "RETRIEVAL_DOCUMENT" hoặc "RETRIEVAL_QUERY"
        # KHÔNG ép output_dimensionality — để Gemini trả default 3072
    }
    # gọi httpx POST {base_url}/embeddings, retry 2x, timeout 30s
```

Public API (giữ nguyên từ Phase 2, không phá caller):

```python
embed_passages(texts)        # -> list[list[float]], task_type=RETRIEVAL_DOCUMENT
embed_query(query)           # -> list[float],      task_type=RETRIEVAL_QUERY
embed_query_batch(queries)   # -> list[list[float]]
build_quiz_text(quiz)        # -> str
build_question_text(q, quiz) # -> str
```

## Code Organization Rationale

**Why a separate `qdrant_service.py`?**

- Single source of truth cho Qdrant client + collection schema.
- `ensure_collections()` là chỗ duy nhất biết schema → dễ thay đổi (thêm field, đổi dim).
- 2 filter (`public_filter` / `chat_filter`) tách rõ giúp tránh leak dữ liệu nhạy cảm.

**Why a separate `embedding_service.py`?**

- Embedding model là swappable dependency.
- Dù là local hay remote API, caller chỉ thấy `embed_query()` / `embed_passages()`.
- `build_*_text()` sống ở đây vì mô tả _what_ được embed, là model concern.

**Why a separate `ingestion_service.py`?**

- Chỗ duy nhất biết PostgreSQL → Qdrant mapping.
- Thêm source type mới (chunk, message, …) chỉ động vào file này, không ảnh hưởng service khác.

**Why is PostgreSQL still the source of truth?**

- Mọi write đi qua Postgres trước.
- Qdrant là derived cache.
- Nếu Qdrant wipe → chạy backfill là recover được.

**Why use quiz/question/message UUID as Qdrant point ID?**

- 1-to-1 tự nhiên, không cần bảng ID riêng.
- Upsert idempotent theo ID.
- Delete by `quiz_id` / `source_id` filter sạch và atomic.

**Why sync ingestion (best-effort)?**

- Quiz/message CRUD là low-frequency (người dùng tạo, không phải bot).
- Best-effort: lỗi Qdrant/embed chỉ log warning, không phá luồng chính. User vẫn CRUD bình thường.
- Nếu sau này cần async, wrap `BackgroundTasks` — signature không đổi.

**Why `is_public` / `is_deleted` / `conversation_id` denormalized in payload?**

- Qdrant không JOIN được với Postgres ở search time.
- Filter phải self-contained trong Qdrant.
- Denormalize gần như miễn phí, bù lại filter cực nhanh không cần roundtrip DB.

## File Layout (hiện tại)

```
backend/
├── app/
│   ├── api/v1/endpoints/
│   │   ├── search.py              # /search/quizzes, /search/questions
│   │   └── messages.py            # thêm /conversations/{id}/messages/search
│   ├── core/
│   │   └── config.py              # EMBEDDING_DIM=3072, QDRANT_VECTOR_SIZE=3072, ...
│   ├── services/
│   │   ├── qdrant_service.py      # client, ensure_collections, public_filter, chat_filter
│   │   ├── embedding_service.py   # httpx → Gemini proxy /embeddings
│   │   ├── llm_service.py         # httpx → Gemini proxy /chat/completions (cho Phase 3)
│   │   ├── ingestion_service.py   # ingest_quiz / ingest_message / reingest_all_messages
│   │   ├── search_service.py      # search_quizzes / search_questions / search_messages
│   │   ├── quiz_service.py        # hook _maybe_ingest_quiz vào CRUD
│   │   └── message_service.py     # hook _maybe_ingest_message vào CRUD
│   └── websockets/
│       └── chat_socket.py         # hook ingest_message cho realtime
├── scripts/
│   └── backfill_embeddings.py     # backfill quiz + question
└── ...
docker-compose.yml                # 7 service, Qdrant TCP healthcheck
env-docker-template.txt           # template .env (copy thành .env ở root)
```

## Troubleshooting

**Q: `ensure_collections()` fails on startup với "connection refused"**

- Qdrant container chưa sẵn sàng. Check `docker compose ps` + `docker compose logs qdrant`.
- Verify `QDRANT_URL` trong backend env = `http://qdrant:6333` (service name trong compose network).
- Qdrant image không có curl/wget → healthcheck dùng TCP port check (`exec 3<>/dev/tcp/127.0.0.1/6333`).

**Q: Search trả 0 results cho query chắc chắn có**

- Check `is_public` + `is_deleted` của quiz.
- Filter mặc định yêu cầu `is_public=true AND is_deleted=false`.
- Verify quiz đã ingest: mở `http://localhost:6333/dashboard`, chọn collection, scroll points, check payload.
- Nếu quiz tạo trước khi deploy Phase 2 → chạy backfill.

**Q: Vector size mismatch error (got 3072, expected 768) — lỗi cũ khi chuyển dim**

- Qdrant collection bị lock dimension tại thời điểm tạo.
- Fix: drop 4 collection cũ + restart backend + backfill lại.

**Q: Re-indexing quiz tạo duplicate?**

- Không — dùng `upsert` với UUID làm point ID.
- Re-run backfill idempotent.

**Q: Search messages trả 403**

- Bạn không phải member của conversation đó. Check `conversation_members`.

**Q: Hook ingestion spam log warning**

- Có thể Gemini proxy / Qdrant chập chờn. Hook là best-effort, không ảnh hưởng CRUD chính.
- Khi proxy healthy, hook tự chạy lại ở lần update tiếp theo (hoặc backfill).

**Q: API key Gemini proxy sai → 401/403 từ proxy**

- LLM/embedding service sẽ raise `RuntimeError`. Hook ingestion sẽ log warning.
- Endpoint search sẽ trả 500 (vì `embed_query()` lỗi).
- Fix: cập nhật `GEMINI_PROXY_API_KEY` trong `.env` rồi `docker compose up -d --force-recreate --no-deps backend`.

**Q: First call chậm**

- Gemini proxy có cold start ~500ms-1s. Sau đó < 200ms.
- Nếu muốn warmup, có thể thêm 1 call `embed_query("warmup")` trong `main.py` startup hook.

**Q: Muốn đổi từ Gemini sang local embedding**

- Revert `embedding_service.py` về `sentence-transformers` (xem git history Phase 2 cũ).
- Đổi `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `QDRANT_VECTOR_SIZE` cho khớp.
- Drop 4 collection + backfill.

## Summary Checklist (hiện tại)

- [x] Qdrant service chạy trên `localhost:6333` (trong compose).
- [x] 4 collection tạo với dim=3072, distance=Cosine, payload indexes idempotent.
- [x] `quiz_embeddings` + `question_embeddings` populated qua quiz CRUD hooks.
- [x] `chat_context_embeddings` populated qua message CRUD + WebSocket hooks.
- [x] `retrieval_chunks` tạo rỗng (reserved).
- [x] `/api/v1/search/quizzes?q=...` trả top-k semantically similar public quizzes.
- [x] `/api/v1/search/questions?q=...` trả top-k semantically similar public questions.
- [x] `/api/v1/conversations/{id}/messages/search?q=...` trả top-k trong 1 conversation (cần membership).
- [x] Filter `is_public=true AND is_deleted=false` cho quiz/question; `is_deleted=false` cho message.
- [x] Backfill script sẵn cho re-indexing.
- [x] `llm_service.py` đã có sẵn, chờ Phase 3 wire-up.
