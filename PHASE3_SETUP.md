# Phase 3: AI Chat Layer (Intent Router + Text-to-SQL + LLM Orchestration)

> **Trạng thái: 📋 PLAN** (chưa implement). Phase 2 đã xong, Phase 3 build trên nền đó.
> Mục tiêu: cho user chat với AI trong 1 conversation, AI dùng LLM + retrieval + (khi cần) truy vấn DB có cấu trúc.

## Tóm tắt 1 dòng

User gửi message → **Intent Router** phân loại (`smalltalk` | `semantic_search` | `text_to_sql` | `mixed`) → chạy tool tương ứng (Qdrant search hoặc whitelisted SQL) → ghép context → gọi LLM `gemini-2.5-flash` qua proxy → trả answer + lưu `ai_runs` audit.

## TL;DR — Câu trả lời cho câu hỏi thường gặp

**Q: Đến Phase 3 đã có text-to-SQL chưa?**
**A: Chưa.** Phase 2 chỉ có semantic search (Qdrant). Text-to-SQL là 1 phần của Phase 3 (phần này tôi sẽ thiết kế bên dưới).

**Q: Làm sao để LLM hiểu bảng để truy vấn whitelist?**
**A: Dùng "schema catalog"** — 1 file/dict khai báo tên bảng, cột, kiểu, quan hệ, kèm mô tả ngắn bằng tiếng Việt/Anh. Catalog này là **nguồn duy nhất** mà router và LLM được thấy. LLM không bao giờ được nhìn thấy raw SQL hay tự sinh SQL truy vấn bảng ngoài catalog.

**Q: Làm sao model LLM biết khi nào dùng search Qdrant, khi nào text-to-SQL, khi nào cả 2?**
**A: Intent Router** — 1 LLM call riêng (rẻ, nhanh, temperature=0) chỉ để phân loại intent + extract params. Router trả JSON `{intent, tool_args, needs_other_tool}`. Orchestrator dựa vào đó gọi tool tương ứng, **không để LLM chính tự quyết**.

---

## 1. Bối cảnh & vì sao cần Intent Router

### Vấn đề nếu không có router

Nếu cứ nhét mọi user message vào LLM kèm toàn bộ schema DB + Qdrant tool description, LLM sẽ:

1. **Hallucinate SQL** — đặc biệt với `gemini-2.5-flash` khi schema phức tạp, LLM dễ bịa bảng/cột.
2. **Tự quyết sai tool** — ví dụ user hỏi "tìm quiz về động vật" (cần semantic search) nhưng LLM chọn text-to-SQL `WHERE title ILIKE '%dong vat%'` (chất lượng kém hơn nhiều).
3. **Prompt phình to** — schema + tool doc + history + context → vượt context window, tốn token, tăng latency.

### Giải pháp

Tách làm 2 bước:

```
User message + recent chat history
   ↓
┌──────────────────────────────────┐
│ Step 1: Intent Router (LLM nhỏ) │   ← chỉ phân loại + extract
│  → {intent, args, needs_*}      │
└──────────────────────────────────┘
   ↓
┌──────────────────────────────────┐
│ Step 2: Tool execution (code)    │   ← chạy thật, deterministic
│  search_quizzes / sql_query /   │
│  get_my_quizzes / smalltalk      │
└──────────────────────────────────┘
   ↓
┌──────────────────────────────────┐
│ Step 3: Answer composer (LLM)    │   ← viết câu trả lời tự nhiên
│  context = tool_result + history │
└──────────────────────────────────┘
   ↓
Reply + lưu ai_runs
```

**Lý do tách 2 LLM call:**

- Router call: prompt cố định, schema nhỏ, temperature=0 → deterministic, rẻ, nhanh (~200-400ms).
- Composer call: chỉ cần format tool_result thành câu trả lời, không cần "biết" schema hay tool.
- Có thể swap router/composer độc lập (vd: router dùng `gemini-2.5-flash-lite` cho rẻ).

---

## 2. Schema Catalog (whitelist cho text-to-SQL)

### Triết lý

LLM chỉ được thấy **catalog**, không được thấy raw DB. Catalog là 1 dict Python (hoặc file YAML) mô tả:

- Bảng nào được phép truy vấn.
- Cột nào được phép select/where.
- Kiểu dữ liệu + enum nếu có.
- Quan hệ FK (chỉ khai báo, không tự generate JOIN phức tạp).
- Mô tả ngắn bằng ngôn ngữ tự nhiên (1-2 câu/bảng, 1 câu/cột quan trọng).
- 1-2 ví dụ query mẫu.

LLM emit JSON `{table, columns, filters, limit, order_by}`. Backend validate chặt chẽ (table ∈ catalog, columns ∈ table whitelist, filter values là scalar hoặc enum) → build SQL bằng SQLAlchemy core (không dùng string concat, chống injection).

### File `backend/app/services/schema_catalog.py` (dự kiến)

```python
# CHỈ là whitelist. Thêm bảng mới = thêm entry ở đây.
# LLM KHÔNG BAO GIỜ truy vấn bảng ngoài catalog này.

SCHEMA_CATALOG = {
    "tables": {
        "quizzes": {
            "description": "Bộ câu hỏi (quiz). Mỗi quiz có nhiều question. is_public=true mới hiện trong search.",
            "columns": {
                "id":             {"type": "uuid", "selectable": False, "description": "Không cần select."},
                "title":          {"type": "string", "selectable": True, "description": "Tiêu đề quiz."},
                "description":    {"type": "string", "selectable": True, "description": "Mô tả ngắn."},
                "is_public":      {"type": "bool",   "selectable": True, "description": "True = công khai."},
                "is_deleted":     {"type": "bool",   "selectable": True, "description": "Soft delete. Luôn filter = false."},
                "created_by":     {"type": "uuid",   "selectable": True, "description": "FK -> users.id."},
                "created_at":     {"type": "datetime","selectable": True, "description": "Ngày tạo."},
                "question_count": {"type": "int",    "selectable": True, "description": "Đếm số question (subquery)."},
            },
            "allowed_filters": ["is_public", "is_deleted", "created_by", "created_at"],
            "allowed_order_by": ["created_at", "title", "question_count"],
        },
        "questions": {
            "description": "Câu hỏi trong quiz. Phải join với quizzes để biết is_public.",
            "columns": {
                "id":            {"type": "uuid",   "selectable": False},
                "quiz_id":       {"type": "uuid",   "selectable": True, "description": "FK -> quizzes.id."},
                "content":       {"type": "string", "selectable": True, "description": "Nội dung câu hỏi."},
                "question_type": {"type": "enum:single_choice,multiple_choice,true_false", "selectable": True},
                "points":        {"type": "int",    "selectable": True},
                "created_at":    {"type": "datetime", "selectable": True},
            },
            "allowed_filters": ["quiz_id", "question_type", "created_at"],
            "allowed_order_by": ["created_at", "points"],
        },
        "users": {
            "description": "Người dùng. KHÔNG được select email/password_hash — chỉ dùng để filter created_by.",
            "columns": {
                "id":           {"type": "uuid",   "selectable": True,  "description": "PK."},
                "username":     {"type": "string", "selectable": True},
                "full_name":    {"type": "string", "selectable": True},
                "created_at":   {"type": "datetime", "selectable": True},
                # email, password_hash, ... KHÔNG khai báo ở đây = không selectable.
            },
            "allowed_filters": ["id", "username", "created_at"],
            "allowed_order_by": ["created_at", "username"],
            "forbidden_columns": ["email", "password_hash"],  # double-check ở runtime
        },
        "game_rooms": {
            "description": "Phòng chơi game. ended_at IS NULL = đang mở.",
            "columns": {
                "id":         {"type": "uuid",   "selectable": True},
                "quiz_id":    {"type": "uuid",   "selectable": True, "description": "FK -> quizzes.id."},
                "host_id":    {"type": "uuid",   "selectable": True, "description": "FK -> users.id."},
                "room_code":  {"type": "string", "selectable": True},
                "status":     {"type": "enum:waiting,playing,ended", "selectable": True},
                "started_at": {"type": "datetime", "selectable": True},
                "ended_at":   {"type": "datetime", "selectable": True, "description": "NULL = chưa kết thúc."},
                "created_at": {"type": "datetime", "selectable": True},
            },
            "allowed_filters": ["status", "host_id", "quiz_id", "created_at", "ended_at"],
            "allowed_order_by": ["created_at", "started_at"],
        },
        "user_stats": {
            "description": "Thống kê tổng hợp của user (tổng trận, tổng điểm, tỷ lệ thắng).",
            "columns": {
                "user_id":           {"type": "uuid",   "selectable": True},
                "total_games":       {"type": "int",    "selectable": True},
                "total_wins":        {"type": "int",    "selectable": True},
                "total_points":      {"type": "int",    "selectable": True},
                "win_rate":          {"type": "float",  "selectable": True, "description": "0.0 - 1.0."},
                "updated_at":        {"type": "datetime", "selectable": True},
            },
            "allowed_filters": ["user_id", "total_games", "win_rate"],
            "allowed_order_by": ["total_points", "total_wins", "win_rate", "updated_at"],
        },
    },

    "joins": {
        # Router có thể yêu cầu JOIN 2 bảng. Phải khai báo ở đây mới cho phép.
        "quizzes__questions": {
            "from": "quizzes", "to": "questions",
            "on": "quizzes.id = questions.quiz_id",
            "description": "Lấy question kèm info quiz.",
        },
        "quizzes__game_rooms": {
            "from": "quizzes", "to": "game_rooms",
            "on": "quizzes.id = game_rooms.quiz_id",
            "description": "Lấy phòng chơi của 1 quiz.",
        },
        "users__user_stats": {
            "from": "users", "to": "user_stats",
            "on": "users.id = user_stats.user_id",
            "description": "Lấy stats kèm thông tin user.",
        },
    },

    "examples": [
        {
            "nl": "Top 5 user có nhiều trận thắng nhất",
            "query": {
                "tables": ["users", "user_stats"],
                "joins": ["users__user_stats"],
                "select": ["users.username", "users.full_name", "user_stats.total_wins"],
                "filters": [],
                "order_by": [{"column": "user_stats.total_wins", "direction": "DESC"}],
                "limit": 5,
            },
        },
        {
            "nl": "Có bao nhiêu quiz public tạo tuần này",
            "query": {
                "tables": ["quizzes"],
                "select": ["COUNT(*) AS count"],
                "filters": [
                    {"column": "is_public", "op": "=", "value": True},
                    {"column": "created_at", "op": ">=", "value": "<last_7_days>"},
                ],
                "order_by": [],
                "limit": 1,
            },
        },
    ],
}
```

### Runtime validation (chống LLM bypass)

Khi nhận JSON query từ LLM:

1. **Table check**: mọi `table` trong query phải có key trong `SCHEMA_CATALOG["tables"]` — nếu không → reject.
2. **Column check**: mọi column trong `select` / `filters` / `order_by` phải ∈ table's column dict, AND `selectable=True` (cho select) hoặc ∈ `allowed_filters` (cho filter).
3. **Join check**: join phải ∈ `joins` dict, 2 bảng join phải match `from`/`to`.
4. **Value check**:
   - Scalar value phải match kiểu (uuid/int/float/bool/str).
   - Enum value phải ∈ enum list.
   - Datetime string: parse bằng `dateutil`, nếu fail → reject.
5. **No raw SQL**: chỉ build SQL bằng SQLAlchemy core (`select(table.c.col).where(...)`). LLM không truyền string SQL.
6. **Row limit**: ép `LIMIT <= 50`. Mặc định 20.
7. **Forbidden columns**: double-check (vd: `email`, `password_hash` không bao giờ select được dù có trong column dict).

---

## 3. Intent Router

### Mục tiêu

Router là 1 LLM call với prompt cố định, schema JSON output, temperature=0. Output dự đoán được, dễ test.

### Intents (closed set)

| Intent              | Khi nào trigger                                     | Tool chạy                       |
| ------------------- | --------------------------------------------------- | ------------------------------- |
| `smalltalk`         | Chào hỏi, hỏi giờ, không liên quan data quiz        | Không gọi tool; composer trả lời thẳng |
| `semantic_search`   | Hỏi tìm quiz/question theo chủ đề mô tả             | `search_quizzes` / `search_questions` / `search_messages` |
| `text_to_sql`       | Hỏi thống kê, đếm, lọc theo metadata cụ thể         | `safe_sql_query` (catalog)      |
| `hybrid`            | Cần cả 2 (vd: "quiz về động vật có trên 50 câu hỏi") | Gọi cả semantic_search + text_to_sql filter |
| `get_my_*`          | User hỏi về data của chính họ (quiz của tôi, stats của tôi) | `text_to_sql` với scope = current_user_id |
| `clarify`           | Không chắc user muốn gì                             | Composer hỏi lại                |

### Output schema (JSON, validated by Pydantic)

```json
{
  "intent": "hybrid",
  "confidence": 0.86,
  "semantic": {
    "collection": "quiz_embeddings",
    "query": "động vật",
    "top_k": 5
  },
  "sql": {
    "tables": ["quizzes"],
    "joins": [],
    "select": ["id", "title", "question_count"],
    "filters": [
      {"column": "question_count", "op": ">", "value": 50},
      {"column": "is_public", "op": "=", "value": true},
      {"column": "is_deleted", "op": "=", "value": false}
    ],
    "order_by": [{"column": "question_count", "direction": "DESC"}],
    "limit": 5
  },
  "merge_strategy": "intersect_ids",  // "intersect_ids" | "concat" | "sql_filter_then_semantic"
}
```

### Prompt template (router system message)

```
Bạn là Intent Router cho Quiz Battle. Nhiệm vụ: phân loại câu hỏi của user và extract tham số.

Intents:
- "smalltalk": chào hỏi, không liên quan quiz/user/stats
- "semantic_search": tìm quiz/question theo chủ đề ngữ nghĩa ("quiz về động vật", "câu hỏi về lịch sử")
- "text_to_sql": truy vấn có cấu trúc (đếm, lọc theo số, thống kê, top X)
- "hybrid": cần cả 2 (vd: "quiz về X có trên N câu hỏi")
- "get_my_*": user hỏi về data của chính họ — sẽ tự scope theo current_user_id
- "clarify": không chắc — để composer hỏi lại

Schema catalog (WHITELIST DUY NHẤT cho text_to_sql — KHÔNG được truy vấn bảng ngoài đây):
<schema_catalog_json>

Conversation history (gần nhất):
<last_5_messages>

User message: "{user_query}"

Trả JSON với schema:
{
  "intent": "...",
  "confidence": 0.0-1.0,
  "semantic": null | {...},
  "sql": null | {...},
  "merge_strategy": "intersect_ids" | "concat" | "sql_filter_then_semantic" | null,
  "reasoning": "1 câu giải thích ngắn"
}

QUY TẮC:
- CHỈ được select/filter cột trong schema catalog.
- Nếu user hỏi thứ ngoài khả năng (vd: "đặt hàng"), set intent="smalltalk" + reasoning.
- KHÔNG tự sinh SQL string. Chỉ trả structured query.
- Khi không chắc, set confidence<0.6 để orchestrator fallback sang clarify.
```

### Validation bằng Pydantic

```python
class RouterOutput(BaseModel):
    intent: Literal["smalltalk", "semantic_search", "text_to_sql", "hybrid", "get_my_quizzes", "get_my_stats", "clarify"]
    confidence: float = Field(ge=0, le=1)
    semantic: Optional[SemanticBlock] = None
    sql: Optional[SqlBlock] = None  # validate bằng SqlBlock(strict=True, catalog=...)
    merge_strategy: Optional[Literal["intersect_ids", "concat", "sql_filter_then_semantic"]] = None
    reasoning: str
```

Pydantic validator sẽ:

- Nếu `intent in {text_to_sql, hybrid, get_my_*}` mà `sql is None` → reject, retry router 1 lần.
- Nếu `sql` không pass schema catalog check → reject, retry router 1 lần.
- Retry 2 lần fail → fallback `clarify`.

### Few-shot examples trong prompt (3-5 ví dụ)

Cố định trong prompt để tăng độ chính xác:

```
Ví dụ 1:
User: "Chào bạn"
→ {"intent": "smalltalk", "confidence": 0.99, ...}

Ví dụ 2:
User: "Tìm quiz về động vật"
→ {"intent": "semantic_search", "confidence": 0.95,
   "semantic": {"collection": "quiz_embeddings", "query": "động vật", "top_k": 5}}

Ví dụ 3:
User: "Top 5 user thắng nhiều nhất"
→ {"intent": "text_to_sql", "confidence": 0.92,
   "sql": {"tables": ["users","user_stats"], "joins": ["users__user_stats"],
           "select": ["users.username","user_stats.total_wins"],
           "order_by": [{"column":"user_stats.total_wins","direction":"DESC"}],
           "limit": 5}}

Ví dụ 4:
User: "Quiz về lịch sử Việt Nam có trên 20 câu hỏi"
→ {"intent": "hybrid", "confidence": 0.88,
   "semantic": {"collection":"quiz_embeddings","query":"lịch sử Việt Nam","top_k":10},
   "sql": {"tables":["quizzes"], "select":["id"],
           "filters":[{"column":"question_count","op":">","value":20},
                      {"column":"is_public","op":"=","value":true},
                      {"column":"is_deleted","op":"=","value":false}]},
   "merge_strategy": "intersect_ids"}
```

---

## 4. Tool implementations (server-side, deterministic)

### 4.1. `semantic_search` tool

Reuse `search_service.search_quizzes / search_questions / search_messages` (đã có ở Phase 2). Thêm 1 wrapper:

```python
def tool_semantic_search(collection: str, query: str, top_k: int,
                          conversation_id: str | None = None) -> list[dict]:
    if collection == "quiz_embeddings":
        return search_quizzes(query, top_k)
    elif collection == "question_embeddings":
        return search_questions(query, top_k)
    elif collection == "chat_context_embeddings":
        if not conversation_id:
            raise ValueError("conversation_id required for chat search")
        return search_messages(query, conversation_id, top_k)
    else:
        raise ValueError(f"Unknown collection: {collection}")
```

### 4.2. `safe_sql_query` tool

```python
def tool_safe_sql_query(query: SqlBlock, current_user_id: UUID | None = None) -> dict:
    """
    Validate query thuộc schema catalog, build SQL bằng SQLAlchemy core, execute, trả dict.
    """
    catalog = get_schema_catalog()
    _validate_query_against_catalog(query, catalog)  # raise nếu invalid

    # 1. Build SQLAlchemy core statement
    stmt = _build_select_statement(query, catalog)

    # 2. Apply row limit
    stmt = stmt.limit(min(query.limit or 20, 50))

    # 3. Execute qua read-only session (DB user chỉ-đọc — optional hardening)
    with engine.connect() as conn:
        result = conn.execute(stmt)
        rows = [dict(r._mapping) for r in result]

    return {"columns": list(rows[0].keys()) if rows else [], "rows": rows, "count": len(rows)}
```

`_build_select_statement` dùng `sqlalchemy.sql.select(table.c.column).where(...)` — không có string concat, không có raw SQL. Mỗi filter op (`=`, `>`, `<`, `>=`, `<=`, `IN`, `LIKE`) có 1 hàm whitelist ánh xạ `op -> sqlalchemy.sql.operators`.

### 4.3. Hybrid merge

`merge_strategy` quyết định cách kết hợp kết quả:

- `sql_filter_then_semantic` (mặc định hybrid): chạy SQL trước lấy whitelist ID, rồi semantic search trong Qdrant với filter `id IN (...)` (Qdrant hỗ trợ filter theo `id` payload).
- `intersect_ids`: lấy intersection giữa ID set từ SQL và ID set từ Qdrant.
- `concat`: chạy cả 2, nối kết quả (dùng cho câu hỏi "liệt kê X và Y").

### 4.4. `get_my_*` shortcut

Khi router emit `intent="get_my_quizzes"`, orchestrator tự inject `filter: created_by = current_user_id` vào `sql` block, không cần LLM phải biết user ID.

---

## 5. Answer composer

Sau khi tools chạy xong, build 1 context object:

```python
@dataclass
class ComposerContext:
    user_query: str
    intent: str
    tool_results: list[dict]      # [{"tool": "semantic_search", "data": [...]}, ...]
    recent_history: list[dict]    # 5 message gần nhất
    current_user_id: UUID
```

System prompt composer:

```
Bạn là trợ lý AI của Quiz Battle. Trả lời user dựa trên:
1. Tool results (dữ liệu có cấu trúc / semantic search)
2. Recent chat history
3. Không bịa thêm data ngoài tool results.

Quy tắc:
- Trả lời bằng tiếng Việt (hoặc ngôn ngữ user dùng).
- Ngắn gọn, dùng bullet/list nếu nhiều kết quả.
- Luôn cite nguồn: "Theo semantic search..." hoặc "Theo database có N quiz...".
- Nếu tool trả 0 kết quả: nói rõ "Hiện không có kết quả phù hợp".
- KHÔNG tự ý thêm thông tin không có trong context.
- Câu hỏi ngoài phạm vi (vd: "thời tiết hôm nay"): lịch sự từ chối.
```

User message composer:

```
User: "{user_query}"

Context:
- Intent: {intent}
- Tool results:
{tool_results_json}
- Recent history:
{history_json}

Hãy soạn câu trả lời.
```

LLM trả text. Backend save vào `messages` (sender_type="ai") + log vào `ai_runs`.

---

## 6. `ai_runs` audit table

### Schema

```sql
CREATE TABLE ai_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    ai_message_id   UUID REFERENCES messages(id) ON DELETE SET NULL,

    -- Routing
    intent          VARCHAR(50) NOT NULL,    -- smalltalk / semantic_search / text_to_sql / hybrid / clarify
    router_raw      JSONB,                   -- raw LLM output từ router
    router_retries  INT NOT NULL DEFAULT 0,

    -- Tool execution
    tool_calls      JSONB,                   -- [{"tool":"semantic_search","args":{...},"result_summary":"5 hits"}, ...]

    -- Prompt snapshot
    composer_system TEXT,
    composer_user   TEXT,
    composer_raw    TEXT,                    -- raw LLM output

    -- Token usage
    prompt_tokens   INT,
    completion_tokens INT,
    total_tokens    INT,
    model_name      VARCHAR(100),

    -- Latency
    router_ms       INT,
    tool_ms         INT,
    composer_ms     INT,
    total_ms        INT,

    -- Error tracking
    error           TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_ai_runs_conversation ON ai_runs(conversation_id, created_at DESC);
CREATE INDEX ix_ai_runs_user_message ON ai_runs(user_message_id);
```

### Tại sao cần

- Debug: khi AI trả sai, mở `ai_runs` xem router đã chọn intent gì, tool gì, kết quả ra sao, prompt nào.
- Cost: tổng token usage theo conversation / user / ngày.
- Eval: tự build dataset (user_query, intent_expected, tool_called) để đánh giá router accuracy theo thời gian.
- A/B test: thay router model, so sánh `intent` distribution.

---

## 7. Luồng end-to-end (sequence)

```
User (WebSocket) ─── SEND_MESSAGE ──→ chat_socket
                                          │
                                          ▼
                                  _handle_chat_send
                                          │
                                  ┌───────┴───────┐
                                  │ Persist user  │
                                  │ message       │
                                  │ (Postgres)    │
                                  └───────┬───────┘
                                          │
                                  _maybe_ingest_message (hook)
                                  (embed → Qdrant, async best-effort)
                                          │
                                          ▼
                              ┌────────────────────────┐
                              │  Detect AI trigger?    │  ← cờ: message starts with
                              │  (vd "@ai ", "/ai")    │     "@ai " hoặc
                              │                        │     tự động nếu conversation
                              │                        │     AI-enabled
                              └────────┬───────────────┘
                                       │ yes
                                       ▼
                              ┌────────────────────────┐
                              │ 1. Intent Router       │  ← llm_service.chat_completion
                              │   (1 LLM call, fast)   │     với router prompt
                              └────────┬───────────────┘
                                       │ RouterOutput
                                       ▼
                              ┌────────────────────────┐
                              │ 2. Validate Pydantic   │
                              │    + catalog check     │  ← fail → retry 1 lần
                              │    + retry if invalid  │     → fail → clarify
                              └────────┬───────────────┘
                                       │ validated
                                       ▼
                              ┌────────────────────────┐
                              │ 3. Run tool(s)         │
                              │    - semantic_search   │  ← parallel nếu hybrid
                              │    - safe_sql_query    │
                              │    - merge if hybrid   │
                              └────────┬───────────────┘
                                       │ tool_results
                                       ▼
                              ┌────────────────────────┐
                              │ 4. Composer (1 LLM)    │  ← llm_service.chat_completion
                              │    trả text answer     │
                              └────────┬───────────────┘
                                       │ answer
                                       ▼
                              ┌────────────────────────┐
                              │ 5. Persist AI message  │
                              │    (sender_type="ai",  │
                              │     is_ai_generated=T) │
                              └────────┬───────────────┘
                                       │
                              ┌────────┴────────┐
                              │ Write ai_runs   │
                              │ (full audit)    │
                              └────────┬────────┘
                                       │
                                       ▼
                              broadcast CHAT_MESSAGE
                              (qua Redis Pub/Sub + ConnectionManager)
```

---

## 8. File / module layout (mới)

```
backend/
├── app/
│   ├── api/v1/endpoints/
│   │   └── ai_chat.py                    # POST /ai/chat (optional REST cho test)
│   ├── services/
│   │   ├── llm_service.py                # có sẵn — thêm chat_completion_with_json() (parse JSON mode)
│   │   ├── intent_router.py              # MỚI — build router prompt, call LLM, parse output
│   │   ├── schema_catalog.py             # MỚI — SCHEMA_CATALOG dict + validators
│   │   ├── sql_tool.py                   # MỚI — safe_sql_query(), _build_select_statement()
│   │   ├── answer_composer.py            # MỚI — build composer prompt, parse answer
│   │   ├── ai_orchestrator.py            # MỚI — glue: router → tool → composer → persist
│   │   ├── search_service.py             # có sẵn — reuse cho semantic tool
│   │   └── ingestion_service.py          # có sẵn — hook vẫn dùng
│   ├── models/ai/
│   │   ├── __init__.py
│   │   └── ai_runs.py                    # MỚI — SQLAlchemy model
│   ├── schemas/
│   │   └── ai.py                         # MỚI — RouterOutput, SqlBlock, SemanticBlock (Pydantic)
│   └── websockets/
│       └── chat_socket.py                # cập nhật — gọi ai_orchestrator khi AI trigger
├── scripts/
│   ├── backfill_embeddings.py            # có sẵn
│   └── backfill_chat_messages.py         # MỚI (hoặc gọi reingest_all_messages trong shell)
└── alembic/                              # cần thêm migration cho ai_runs (nếu có Alembic)
    └── versions/
        └── xxxx_add_ai_runs.py
```

---

## 9. Tasks (chia nhỏ để estimate)

### Task 20: Schema catalog + SQL tool
- [ ] Tạo `schema_catalog.py` với 5-6 bảng whitelist (quizzes, questions, users, game_rooms, user_stats, conversations).
- [ ] Viết `_validate_query_against_catalog()` (table, column, filter, op, value type).
- [ ] Viết `_build_select_statement()` dùng SQLAlchemy core.
- [ ] Viết `tool_safe_sql_query()` với row limit, timeout.
- [ ] Unit test 10 case: valid query, invalid table, invalid column, SQL injection attempt, forbidden column, type mismatch, value too long, etc.

### Task 21: Intent Router
- [ ] Tạo `schemas/ai.py` với `RouterOutput`, `SqlBlock`, `SemanticBlock` (Pydantic strict).
- [ ] Viết `intent_router.py`: build prompt (catalog + history + query), call LLM, parse JSON, validate.
- [ ] Retry logic: 1 lần nếu validation fail, fallback `clarify` nếu vẫn fail.
- [ ] Test 20-30 case manual + assert intent accuracy > 80%.

### Task 22: AI orchestrator
- [ ] Tạo `ai_orchestrator.py`: nhận user_message + conversation_id + current_user_id.
- [ ] Gọi router → validate → chạy tool(s) → merge → composer → persist.
- [ ] Handle timeout từng bước (router 5s, tool 10s, composer 15s).
- [ ] Log structured để debug.

### Task 23: ai_runs table + audit
- [ ] Tạo model `app/models/ai/ai_runs.py`.
- [ ] Alembic migration (hoặc fallback `create_all()`).
- [ ] Wire vào orchestrator: ghi 1 row / 1 AI reply, kèm timing + token.

### Task 24: WebSocket trigger
- [ ] Sửa `chat_socket._handle_chat_send`: sau khi persist user message, check AI trigger (prefix `@ai ` hoặc conversation flag `ai_enabled`).
- [ ] Nếu trigger: gọi `ai_orchestrator.run()` trong background task (không block broadcast user message).
- [ ] Broadcast AI reply qua cùng channel `CHAT_MESSAGE` với `sender_type="ai"`.

### Task 25: Conversation flag
- [ ] Thêm column `ai_enabled BOOLEAN DEFAULT FALSE` vào bảng `conversations`.
- [ ] Endpoint `PATCH /conversations/{id}` cho phép toggle.
- [ ] UI: switch "Bật AI trợ lý" trong ChatWindow (frontend làm ở sprint sau).

### Task 26: Frontend (deferred)
- [ ] Hiển thị AI message với badge "AI" + skeleton loading.
- [ ] Indicator "AI đang trả lời..." (dựa trên typing event).
- [ ] Feedback 👍/👎 cho mỗi AI reply → ghi vào `ai_runs.feedback` (sau này).

### Task 27: Eval + iteration
- [ ] Build dataset 50 câu: intent_expected + tool_expected + answer_quality_score.
- [ ] Đánh giá router accuracy, composer helpfulness, latency p95.
- [ ] Nếu accuracy < 80%: thêm few-shot examples, thử model lớn hơn (`gemini-2.5-pro`).

---

## 10. Security checklist

- [ ] **Không bao giờ** truyền raw SQL string vào LLM prompt.
- [ ] **Không bao giờ** cho LLM select cột nhạy cảm (`email`, `password_hash`, `token`, `secret`).
- [ ] **Luôn** scope `created_by = current_user_id` cho `get_my_*` query (orchestrator tự inject, không tin LLM).
- [ ] **Không** cho LLM truy cập bảng ngoài catalog. Nếu LLM cố (vd: hack prompt), Pydantic validator reject.
- [ ] **Rate limit** theo `current_user_id`: tối đa N AI replies / phút (vd: 10).
- [ ] **Token budget** per user / per day (vd: 100K tokens/ngày). Nếu vượt → trả "Bạn đã dùng hết quota AI hôm nay".
- [ ] **Audit log** mọi AI call vào `ai_runs` (kể cả khi fail) — bắt buộc cho compliance.
- [ ] **PII redaction** trước khi ghi vào `ai_runs.composer_user` (vd: thay email bằng `<email>`).

---

## 11. Cost / latency ước lượng

Mỗi AI reply = 2 LLM call (router + composer) + 1-2 tool call (Qdrant / SQL).

| Bước              | Latency p50  | Latency p95  | Cost / call (proxy Gemini) |
| ----------------- | ------------ | ------------ | -------------------------- |
| Router            | 300ms        | 800ms        | ~$0.0001 (gemini-2.5-flash) |
| Tool (Qdrant)     | 50ms         | 200ms        | $0                         |
| Tool (SQL)        | 20ms         | 100ms        | $0                         |
| Composer          | 500ms        | 1500ms       | ~$0.0003 (gemini-2.5-flash) |
| **Tổng**          | **~900ms**   | **~2.5s**    | **~$0.0004/reply**         |

Với 1K user × 10 reply/ngày = 10K reply/ngày = **~$4/ngày** = **~$120/tháng**. Acceptable cho giai đoạn MVP. Nếu scale 10× có thể:

- Router dùng `gemini-2.5-flash-lite` (rẻ hơn 5×, chỉ cần phân loại).
- Cache router output cho query phổ biến (vd: "tìm quiz về X" → cache 1 giờ).
- Composer gọi batch khi nhiều message queue (ít khả thi vì cần user response nhanh).

---

## 12. Out of scope (Phase 4+)

- ❌ Reranking layer (cross-encoder rerank top-k Qdrant results).
- ❌ Caching retrieval (Redis cache cho popular queries).
- ❌ Long-term memory (vector store user-level preference, tự tham chiếu quá khứ).
- ❌ Voice / image input.
- ❌ Multi-agent (1 agent router, 1 agent SQL, 1 agent composer — overkill cho MVP).
- ❌ Streaming response (cần proxy support SSE; check sau).

---

## 13. Acceptance criteria cho "Phase 3 done"

1. ✅ User gửi "@ai tìm quiz về động vật" → nhận AI reply liệt kê 3-5 quiz phù hợp (có title + question_count + description).
2. ✅ User hỏi "top 5 user thắng nhiều nhất" → nhận AI reply với bảng username + total_wins.
3. ✅ User hỏi "quiz về lịch sử có trên 20 câu hỏi" → hybrid trả kết quả vừa khớp chủ đề vừa khớp số câu.
4. ✅ User hỏi "email của user X" → AI từ chối lịch sự (catalog không cho select email).
5. ✅ User hỏi "drop table users" → AI từ chối (intent=clarify, reasoning "không thể thực hiện").
6. ✅ Mỗi AI reply có 1 row trong `ai_runs` với đầy đủ router output, tool calls, prompt, token usage, latency.
7. ✅ Latency p95 < 3s cho end-to-end.
8. ✅ Router accuracy > 80% trên 30 câu test mẫu.
9. ✅ Không có SQL injection (Pydantic + SQLAlchemy core guard).
10. ✅ Rate limit: user spam 20 message liên tục → 10 reply, 10 bị từ chối "rate limited".

---

## 14. Open questions (cần quyết trước khi code)

1. **Có cần guard "AI chỉ trả lời về quiz/user/stats" không?** Hay cho AI trả smalltalk thoải mái?
   → Đề xuất: cho phép smalltalk (UX tốt hơn), nhưng composer system prompt có guard "nếu ngoài phạm vi thì từ chối lịch sự".
2. **Có cần streaming (SSE) không?** Proxy `api.shopaikey.com` có hỗ trợ stream không?
   → Phase 3 MVP: chờ full response. Nếu user complain latency → thêm stream.
3. **Router có dùng model riêng (gemini-2.5-flash-lite) hay dùng chung gemini-2.5-flash?**
   → Đề xuất: dùng chung `LLM_MODEL` (đơn giản), đổi sau nếu cần tối ưu cost.
4. **Composer có được dùng tool (function calling) không?**
   → Đề xuất Phase 3 MVP: KHÔNG. Tool đã chạy ở bước orchestrator. Composer chỉ format text. Function calling + open-ended tool dễ hallucinate hơn structured router.
5. **`ai_runs.composer_user` có lưu raw history không?** Có thể vi phạm privacy nếu history chứa PII.
   → Đề xuất: lưu summary thay vì raw, hoặc redact email/phone trước khi lưu.
6. **Có cần guard "AI không trả lời về cách hack hệ thống" không?**
   → Composer system prompt có 1 dòng: "Từ chối trả lời nếu user hỏi về SQL injection, exploit, hoặc hành vi gây hại hệ thống."

---

## 15. Migration từ Phase 2 → Phase 3

1. Chạy Alembic (hoặc `create_all()`) để tạo bảng `ai_runs`.
2. Thêm column `ai_enabled` vào `conversations` (default FALSE — opt-in).
3. Thêm `INTENT_ROUTER_PROMPT` + `COMPOSER_PROMPT` vào config (cho phép chỉnh prompt ở 1 chỗ).
4. Tạo feature flag `AI_CHAT_ENABLED=true` trong `.env`. Mặc định OFF để rollout an toàn.
5. Bật cho 1 vài user nội bộ test trước khi rollout toàn user.

---

## 16. References

- `RAG.md` mục 22 — Migration Note Gemini proxy.
- `PHASE2_SETUP.md` — Phase 2 architecture.
- `PHASE3_GEMINI_MIGRATION.md` — Note ngắn về chuyển sang Gemini (hiện đã merge vào PHASE2_SETUP).
- `task.md` — danh sách task Phase 3 (sẽ thêm Task 20-27 ở đây).
