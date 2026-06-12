# CHAT_RAG_ISSUE.md — Quản lý vấn đề cần giải quyết tiếp theo

File này track các vấn đề kỹ thuật còn tồn đọng trong pipeline AI của Quiz Battle,
đặc biệt liên quan đến (1) nới lỏng whitelist SQL, (2) intent router thực sự
query DB thay vì hardcode, và (3) RAG vector search trong chat context.

> Mục đích: tracking + acceptance criteria. **CHƯA implement**, chờ ưu tiên.

---

## 1. Nới lỏng whitelist SQL — text-to-SQL thực sự cover nhiều trường

### 1.1 Hiện trạng

- File: `backend/app/services/sql_validator.py`, `backend/app/services/intent_router.py`
- Catalog đang whitelist khá hẹp:
  - `quizzes`, `user_stats`, `friendships`, `questions`, `users`, `user_responses`
  - Một số bảng thực tế chưa được khai báo trong catalog (vd: `user_achievements`, `rooms`, `room_players`, `quizzes_tags`, `tags`, `notifications`)
- Hiện tại khi user hỏi *"Có bao nhiêu quiz được tạo trong tuần qua?"* → router có thể classify `text_to_sql` nhưng sẽ fail validation vì:
  - Filter dùng `created_at` với placeholder `<last_7_days>` (đã support) ✓
  - Nhưng nếu user hỏi *"Top 3 quiz nào được chơi nhiều nhất"* → cần JOIN `user_responses` + `quizzes` + `GROUP BY` + aggregate → fail vì whitelist JOIN quá giới hạn.

### 1.2 Vấn đề cụ thể

| Thiếu | Ảnh hưởng | Ví dụ user |
|---|---|---|
| JOIN nâng cao (3+ bảng) | Không query được analytics | "Quiz nào có tỉ lệ đúng cao nhất?" → cần JOIN quiz → questions → responses |
| Aggregate (`COUNT`, `AVG`, `SUM`, `MIN`, `MAX`, `GROUP BY`) | Không có thống kê | "Trung bình mỗi user chơi bao nhiêu quiz?" |
| Subquery / CTE | Không query lồng | "Quiz nào mà chưa ai chơi?" |
| Date functions (`DATE_TRUNC`, `EXTRACT`, `INTERVAL`) | Time-series phức tạp | "Đếm quiz theo tháng trong 6 tháng qua" |
| Bảng `tags`, `quizzes_tags`, `quiz_collections` | Không filter theo tag | "Quiz nào có tag 'Lịch sử'?" |
| Bảng `user_achievements`, `badges` | Không query thành tích | "Tôi đã đạt được badge nào?" |
| Bảng `rooms`, `room_players` | Không thống kê phòng | "Phòng nào đông người chơi nhất tuần qua?" |
| Bảng `notifications` | Không query thông báo | "Có bao nhiêu thông báo chưa đọc?" |
| Window functions (`ROW_NUMBER`, `RANK`, `LAG`) | Không có ranking | "Xếp hạng user theo điểm tuần" |

### 1.3 Acceptance criteria

- [ ] Catalog trong `intent_router.py` chứa đầy đủ schema thực tế (sync từ Alembic migration).
- [ ] Validator chấp nhận:
  - JOIN tối đa 3 bảng (giới hạn để tránh cartesian explosion)
  - `GROUP BY` + `COUNT/AVG/SUM/MIN/MAX`
  - Subquery trong `WHERE col IN (SELECT ...)`
  - `DATE_TRUNC`, `EXTRACT`, `INTERVAL`
  - `LIMIT` bắt buộc (chống dump full table)
- [ ] `aggregation_columns` whitelist rõ ràng (`COUNT(*)`, `SUM(score)`, etc).
- [ ] Test cases:
  - "Quiz nào được chơi nhiều nhất tuần qua?" → SQL hợp lệ
  - "Có bao nhiêu user đăng ký mỗi tháng trong 6 tháng qua?" → DATE_TRUNC OK
  - "Tỉ lệ trả lời đúng trung bình của quiz X?" → JOIN responses OK
- [ ] Auto-reject nếu:
  - Không có `LIMIT`
  - JOIN > 3 bảng
  - SELECT có cột nhạy cảm (`password_hash`, `email` nếu không phải self)

### 1.4 Trade-offs

- **Nới rộng → mạnh hơn nhưng rủi ro injection / dump data lớn.** Cần sandbox DB user với permission giới hạn (chỉ SELECT, không DELETE/UPDATE, không truy cập bảng admin).
- **Có thể tốn token** vì catalog dài hơn → cân nhắc nạp schema theo intent thay vì load full catalog.

---

## 2. Intent Router phải thực sự làm sao để backend query được DB rồi ném cho LLM

### 2.1 Hiện trạng

- File: `backend/app/services/intent_router.py`, `backend/app/services/ai_orchestrator.py`
- Hiện tại pipeline:
  ```
  User query
    → Router LLM (call #1) → RouterOutput (intent + sql/semantic block)
      → Orchestrator tự build/get args
        → Tool execution
          → Composer LLM (call #2) → answer
  ```
- Vấn đề: **router chỉ trả structured query, nhưng lại quá phụ thuộc vào catalog được nhúng trong prompt** (~3000 tokens chỉ để mô tả schema). Khi catalog phình to (mục 1) thì router sẽ:
  - Tốn token
  - Dễ hallucinate cột không tồn tại
  - Sửa schema phải redeploy backend (rebuild prompt)

### 2.2 Vấn đề cụ thể

- Router "ảo tưởng" quyền năng — LLM thấy catalog đầy đủ, tự tin build SQL, nhưng thực tế backend vẫn phải validate lại 1 lần nữa ở `sql_validator.py`. → **Hai lớp validation**, redundant.
- Khi schema thay đổi (thêm bảng, sửa cột) → phải edit **2 chỗ**: catalog trong router + SQLAlchemy model. Dễ drift.
- Router không biết "user hiện có bao nhiêu quiz" để gợi ý `LIMIT` hợp lý.

### 2.3 Đề xuất 2 hướng

#### Hướng A: Function-calling thay vì parse JSON

- Dùng Gemini/OpenAI **function calling** (native tool use) thay vì ép LLM trả JSON rồi parse.
- Pro:
  - Schema validation tự động (LLM trả theo function signature → reject nếu thiếu field)
  - Multi-turn tự nhiên (LLM gọi lại function nếu thiếu data)
  - Không cần prompt "luôn trả JSON hợp lệ"
- Con:
  - Phải refactor toàn bộ router
  - Một số proxy (vd shopaikey) có thể chưa support function calling tốt

#### Hướng B: Backend preflight + router chỉ chọn intent

- Bước 1: Backend tự check "user X có quiz không?", "có bao nhiêu bạn bè?"... trước.
- Bước 2: Router LLM chỉ cần chọn `intent` + `query string` (semantic) hoặc `query_type` (cho text_to_sql).
- Bước 3: Backend tự build SQL từ intent + preflight data, KHÔNG để LLM viết SQL.
- Pro:
  - An toàn hơn (LLM không chạm SQL thô)
  - Catalog trong prompt nhỏ hơn nhiều (chỉ cần list bảng + ý nghĩa, không cần full schema)
  - Dễ thêm/sửa schema — không phải rebuild prompt
- Con:
  - Mất flexibility (LLM không thể tự do combine filter)
  - Phải code nhiều path cho mỗi intent

### 2.4 Acceptance criteria

- [ ] Chọn hướng A hoặc B (khuyến nghị **B** vì an toàn hơn cho production).
- [ ] Nếu hướng B: router prompt < 1500 tokens (so với hiện tại ~3000).
- [ ] Backend preflight cache trong Redis để không query DB mỗi message (vd: `user:{id}:stats` TTL 60s).
- [ ] Test:
  - "Tôi có bao nhiêu quiz?" → intent=get_my_quizzes, không cần router biết schema
  - "Quiz nào nhiều người chơi nhất?" → intent=text_to_sql + query type "popular_quizzes" → backend build SQL từ template
- [ ] Mỗi intent text_to_sql có 1 SQL template được review bởi dev, LLM chỉ chọn template + parameters.

---

## 3. RAG vector DB Qdrant trong chat — Tìm chuẩn message liên quan

### 3.1 Hiện trạng

- File: `backend/app/services/ingestion_service.py`, `backend/app/services/search_service.py`, `backend/app/services/ai_orchestrator.py` (bước 2.5)
- Collection: `chat_context_embeddings` (vector size 3072, cosine)
- Hiện tại pipeline:
  1. Message được tạo/update → `_maybe_ingest_message()` → embed + upsert vào Qdrant
  2. User hỏi AI → orchestrator gọi `search_messages(query, conversation_id, top_k=5)`
  3. Top-5 hits được inject vào composer prompt

### 3.2 Vấn đề cụ thể (từ user report)

> *"hôm qua cậu ấy bảo là nên làm gì cho bài toán này thì ranking top 10 hay top k gì đó rồi ném cho LLM"*

#### Bug/limitation đã thấy:

1. **Top-K quá cứng** — luôn `top_k=5` (cố định trong config). Nếu user hỏi "tóm tắt 50 tin nhắn gần nhất" → RAG trả 5 hit gần nhất semantic → miss context.
2. **Không có time-decay** — message từ 2 tháng trước có cùng weight với message từ 2 phút trước. Nếu user hỏi "hôm qua" thì hit từ 2 tháng trước có thể đứng đầu (cùng score cosine).
3. **Không có re-rank** — chỉ raw cosine similarity. Tin nhắn chứa từ khoá chính xác "bài toán" có thể bị đẩy xuống vì semantic score thấp hơn.
4. **Hybrid search chưa có** — chỉ pure vector search. Query như "anh Long nói ID = 123" → vector không hiểu "ID = 123" (số), chỉ hiểu "anh Long nói".
5. **Conversation-level filter chỉ ở Qdrant** — không có filter phụ (vd: "chỉ tin nhắn của sender X"). Nếu user hỏi "tôi đã nói gì về X?" → RAG trả cả tin nhắn của người khác, làm nhiễu.
6. **Metadata lưu ít** — chỉ `{sender_id, sender_type, is_ai_generated, content}`. Thiếu:
   - `sender_name` (phải lookup DB để biết tên hiển thị)
   - `message_id` (để reference back)
   - `created_at` ISO string (để composer nói "tin nhắn lúc 10:30 sáng nay")
   - `reply_to_message_id` (thread context)
7. **Composer prompt chưa tận dụng context** — trong `_build_composer_messages`, mỗi hit chỉ format `[N] sender=UUID, type=user, content=...`. UUID vô nghĩa với LLM, không biết đó là ai. → Trích dẫn kém.

### 3.3 Acceptance criteria cho từng phần

#### 3.3.1 Dynamic top-K

- [ ] Top-K không cứng mà scale theo:
  - Length query (câu dài → cần nhiều context)
  - Intent (summarize → 20-50, lookup → 3-5)
  - Conversation size (conv < 20 msg → trả hết, > 100 → cap 15)
- [ ] Config: `CHAT_RAG_TOP_K_BY_INTENT = {"summarize": 30, "lookup": 5, "default": 8}`
- [ ] Không bao giờ trả > 30 hit (tránh vượt context window LLM)

#### 3.3.2 Time-decay / recency boost

- [ ] Score cuối = `cosine * (1 + alpha * recency_factor)`
  - `recency_factor = exp(-days_since / halflife_days)`, halflife = 7 ngày
- [ ] Hoặc dùng Qdrant `formula` aggregation: `score * exp(-(now - created_at) / 7d)`
- [ ] Test: query "hôm qua" → hit trong 24h qua phải nằm trong top 3

#### 3.3.3 Re-rank với LLM

- [ ] Sau khi lấy top-20 từ Qdrant, gọi LLM nhỏ (hoặc LLM chính) re-rank lại:
  ```
  Query: "{user_query}"
  Candidates:
  1. {hit1}
  2. {hit2}
  ...
  Return: ranked list of indices with reasoning.
  ```
- [ ] Trade-off: tốn thêm 1 LLM call (~300 tokens). Chỉ enable khi `chat_context_rag.count >= 10`.
- [ ] Cache re-rank result theo `(query_hash, candidate_ids)` trong Redis 5 phút.

#### 3.3.4 Hybrid search (vector + keyword)

- [ ] Kết hợp BM25 (PostgreSQL `ts_vector` hoặc Qdrant sparse vector) + dense vector.
- [ ] Tham khảo: Qdrant `SparseVector` + `DenseVector` + RRF (Reciprocal Rank Fusion).
- [ ] Test: query "anh Long nói ID 123" → phải hit được message chứa literal "ID 123".

#### 3.3.5 Richer metadata trong payload

- [ ] Khi ingest message, lưu thêm:
  ```python
  {
    "source_type": "chat_message",
    "conversation_id": "...",
    "message_id": "...",
    "sender_id": "...",
    "sender_name": "Nguyễn Văn Long",   # ← mới
    "sender_type": "user",
    "is_ai_generated": false,
    "content": "...",
    "created_at": "2026-06-11T15:30:00Z",  # ISO string, không phải timestamp
    "reply_to_message_id": null,
    "conversation_type": "direct",  # direct / group
  }
  ```
- [ ] Backfill: script `reingest_all_messages()` phải update cả `sender_name`.

#### 3.3.6 Composer prompt tận dụng metadata

- [ ] Format hit trong prompt:
  ```
  [1] Nguyễn Văn Long (user) — 2026-06-11 15:30
      "Nên dùng dynamic programming cho bài toán này"
  ```
  (Thay vì `sender=abc-uuid, type=user`)
- [ ] LLM trích dẫn được tên + thời gian trong answer.

#### 3.3.7 Conversation filter nâng cao

- [ ] Hỗ trợ filter phụ trong query:
  - `sender_id IN (...)` — "tôi đã nói gì"
  - `is_ai_generated = false` — "có ai nói ngoài AI"
  - `created_at > now - interval` — "trong 24h qua"
- [ ] Router có thể set filter conditions khi classify intent chat_lookup.

### 3.4 Cải thiện UX output

- [ ] Composer LUÔN gắn citation khi dùng chat context:
  > *"Theo lịch sử chat, Nguyễn Văn Long nói lúc 15:30 ngày 11/06: 'Nên dùng dynamic programming...'"*
- [ ] Nếu hit nào có `score < threshold` (vd < 0.5) → gắn marker `[độ liên quan thấp]` để LLM cân nhắc.

### 3.5 Trade-offs

| Cải thiện | Pro | Con |
|---|---|---|
| Dynamic top-K | Linh hoạt hơn | Phải tune per intent |
| Time-decay | Hit gần đây lên top | Có thể bỏ sót "kiến thức nền" cũ |
| Re-rank LLM | Relevant hơn nhiều | +1 LLM call, tốn token, +200-500ms |
| Hybrid (BM25+vector) | Hit được keyword đặc biệt | Phức tạp hơn, cần Qdrant SparseVector |
| Richer metadata | LLM trích dẫn tốt hơn | Payload nặng hơn (~+200 bytes/point) |
| Filter phụ | Chính xác hơn cho query cụ thể | Catalog filter phải mở rộng |

### 3.6 Đề xuất thứ tự làm

1. **Quick win (1-2 ngày)**: Richer metadata (3.3.5) + Composer format tốt hơn (3.3.6). Không đụng Qdrant logic, chỉ enrich payload + prompt.
2. **Medium effort (3-5 ngày)**: Dynamic top-K (3.3.1) + Time-decay (3.3.2).
3. **Advanced (1 tuần+)**: Re-rank LLM (3.3.3) + Hybrid search (3.3.4) + Filter nâng cao (3.3.7).

---

## 4. Tổng hợp — Ưu tiên đề xuất

| # | Vấn đề | Effort | Impact | Đề xuất |
|---|---|---|---|---|
| 1 | RAG richer metadata + composer format | 1-2d | ★★★★ | Làm NGAY (quick win) |
| 2 | Nới lỏng whitelist SQL (1.3) | 3-5d | ★★★★ | Làm trong sprint tiếp |
| 3 | Router preflight + drop SQL (2.4 hướng B) | 1 tuần | ★★★★★ | Làm sau khi SQL whitelist xong |
| 4 | Dynamic top-K + time-decay (3.3.1, 3.3.2) | 3-5d | ★★★ | Parallel với #1 |
| 5 | Hybrid search + re-rank (3.3.3, 3.3.4) | 1 tuần+ | ★★★★ | Sau khi RAG v1 ổn định |
| 6 | Composer LLM strict tool-only answer | 1-2d | ★★★ | Làm song song |

---

## 5. File tham chiếu cần đụng khi implement

- `backend/app/services/intent_router.py` — catalog + classify
- `backend/app/services/sql_validator.py` — whitelist + validator
- `backend/app/services/sql_tool.py` — execute SQL
- `backend/app/services/sql_query_tool.py` — hybrid + fallback
- `backend/app/services/ai_orchestrator.py` — pipeline chính (đã có RAG step 2.5)
- `backend/app/services/ingestion_service.py` — embed chat messages
- `backend/app/services/search_service.py` — query Qdrant
- `backend/app/services/llm_service.py` — Gemini proxy wrapper
- `backend/app/core/config.py` — settings
- `backend/app/schemas/ai.py` — RouterOutput / SqlBlock / SemanticBlock

---

**Status**: 🟡 Đang track, CHƯA implement
**Owner**: TBD
**Created**: 2026-06-12
**Last updated**: 2026-06-12
