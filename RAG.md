# RAG cho mạng xã hội thu nhỏ của Quiz Battle

Tài liệu này mô tả hướng mở rộng từ hệ thống quiz hiện tại sang một lớp AI hỗ trợ chat riêng, có khả năng:

- chat 1-1 hoặc nhóm giữa người dùng;
- dùng lịch sử chat của đúng conversation làm ngữ cảnh;
- tìm quiz/question public bằng embedding trong PostgreSQL;
- kết hợp semantic search và text-to-SQL để trả lời chính xác hơn.

## 1. Mục tiêu

Mục tiêu không phải cho AI đọc toàn bộ database, mà là để AI chọn đúng nguồn dữ liệu trước khi trả lời.

Các nguồn dữ liệu chính:

- lịch sử chat của conversation hiện tại;
- quiz public;
- question thuộc các quiz public;
- metadata có cấu trúc như độ khó, tag, thời gian tạo, số câu hỏi, trạng thái public/private.

Kết quả mong muốn:

- người dùng hỏi bằng ngôn ngữ tự nhiên;
- hệ thống tự quyết định cần semantic search, SQL filter, hay kết hợp cả hai;
- AI trả lời ngắn gọn, có ngữ cảnh, và chỉ dựa trên dữ liệu được phép.

## 2. Hiện trạng trong codebase

Hiện tại backend đã có các phần nền tảng sau:

- auth và user identity ở `backend/app/models/user_auth/users.py`;
- quiz content ở `backend/app/models/quiz/quizzes.py` và `backend/app/models/quiz/questions.py`;
- chat trong game ở `backend/app/models/game/chat_messages.py`;
- realtime WebSocket ở `backend/app/websockets/game_socket.py`;
- Redis Pub/Sub ở `backend/app/services/redis_pubsub.py`.

Điểm quan trọng:

- `chat_messages` hiện tại chỉ phù hợp cho chat trong phòng game;
- `Quiz` đã có `is_public` và `is_deleted`, nên có thể dùng làm nguồn public cho RAG;
- `Question` đã đủ dữ liệu để embed và search semantic;
- auth hiện tại đủ để làm gốc định danh cho social chat và AI.

## 3. Kiến trúc đích

### 3.1 Ba lớp chính

1. Lớp chat và social

- friend request;
- friendship;
- conversation;
- conversation members;
- messages.

2. Lớp retrieval

- embeddings cho quiz và question;
- tìm top-k bằng vector similarity;
- lọc theo metadata bằng SQL.

3. Lớp AI orchestration

- nhận input từ chat;
- phân loại intent;
- gọi semantic search hoặc text-to-SQL tool;
- ghép context;
- gọi model;
- lưu response lại vào messages.

### 3.2 Luồng tổng thể

```text
User message
  -> intent router
  -> if semantic retrieval: embed query -> vector search
  -> if structured query: safe text-to-SQL / whitelisted filters
  -> build context
  -> call LLM
  -> save AI response
  -> broadcast realtime
```

## 4. Data model đề xuất

### 4.1 Social layer

Toàn bộ FK chỉ trỏ về `users.id`.

Các bảng tối thiểu:

- `friend_requests`
  - `id`
  - `requester_id`
  - `addressee_id`
  - `status`
  - `created_at`
  - `updated_at`

- `friendships`
  - `id`
  - `user_id_1`
  - `user_id_2`
  - `created_at`

- `conversations`
  - `id`
  - `type` (`direct`, `group`)
  - `direct_key` cho conversation direct 1-1
  - `title`
  - `created_at`
  - `updated_at`
  - `last_message_at`

- `conversation_members`
  - `id`
  - `conversation_id`
  - `user_id`
  - `role`
  - `last_read_at`
  - `joined_at`

- `messages`
  - `id`
  - `conversation_id`
  - `sender_id`
  - `sender_type` (`user`, `ai`, `system`)
  - `content`
  - `is_ai_generated`
  - `metadata` JSONB
  - `created_at`
  - `updated_at`
  - `deleted_at`

### 4.2 Retrieval layer cho quiz

Có 2 mức embedding:

- `quizzes` embedding cho toàn bộ quiz;
- `questions` embedding cho từng câu hỏi.

Nếu muốn mở rộng rõ ràng hơn, vector data nên được đẩy sang Qdrant thay vì giữ trong PostgreSQL.

Trong Qdrant, mỗi record là một `point` gồm:

- `id`;
- `vector`;
- `payload`.

Nên tổ chức theo collection riêng:

- `quiz_embeddings`;
- `question_embeddings`;
- `retrieval_chunks` nếu cần chunk dài;
- `chat_context_embeddings` nếu sau này muốn embed lịch sử chat phục vụ AI.

Payload của point nên lưu:

- `source_type` (`quiz`, `question`, `chunk`, `chat_message`);
- `source_id`;
- `quiz_id`;
- `conversation_id` nếu có;
- `is_public`;
- `is_deleted`;
- `chunk_index`;
- metadata bổ sung như `title`, `difficulty`, `tag`.

Qdrant phù hợp hơn pgvector khi muốn:

- tách vector store ra khỏi PostgreSQL;
- scale retrieval độc lập;
- rebuild index hoặc thay embedding model mà không ảnh hưởng dữ liệu nghiệp vụ;
- giữ PostgreSQL làm source of truth cho nghiệp vụ.

Nếu vẫn muốn giai đoạn đầu đơn giản, có thể khởi đầu bằng PostgreSQL, nhưng tài liệu đích nên coi Qdrant là vector layer chính.

Qdrant sẽ lưu vector, còn PostgreSQL vẫn lưu dữ liệu chuẩn như quiz, question, conversation, message, audit.

### 4.3 Bảng phục vụ AI audit

Nên thêm một bảng để biết AI đã trả lời dựa trên gì:

- `ai_runs`
  - `id`
  - `conversation_id`
  - `user_message_id`
  - `model_name`
  - `intent`
  - `retrieval_mode`
  - `retrieved_refs` JSONB
  - `prompt_snapshot` JSONB hoặc text
  - `token_usage`
  - `created_at`

Mục đích của bảng này là debug và audit, không phải để hiển thị cho người dùng.

## 5. Qdrant vector search

### 5.1 Qdrant vận hành kiểu gì

Qdrant lưu embeddings theo collection, và mỗi point có thể map ngược về bản ghi gốc bằng `id` hoặc `payload.source_id`.

Ý tưởng:

- lưu vector embedding vào Qdrant collection;
- tạo index vector nội bộ của Qdrant;
- truy vấn top-k gần nhất bằng cosine distance hoặc tương đương;
- dùng payload để lọc trước khi rerank.

### 5.2 Query shape

Một query RAG điển hình sẽ là:

1. embed câu hỏi user;
2. tìm top-k candidates trong Qdrant;
3. lọc bằng payload, ví dụ public/private, deleted, type, tag;
4. lấy thêm dữ liệu chi tiết từ PostgreSQL nếu cần;
5. rerank candidates;
6. đưa context tốt nhất vào prompt.

### 5.3 Nguồn text để embed

Nên embed từ các trường sau:

- `quiz.title`;
- `quiz.description`;
- `question.content`;
- tag;
- độ khó;
- mô tả category nếu có.

Ví dụ cách ghép text cho 1 question:

```text
Quiz title: ...
Quiz description: ...
Question: ...
Tag: ...
Difficulty: ...
```

### 5.4 Truy vấn semantic

User hỏi: “Có bộ quiz nào liên quan tới con vật không?”

Backend làm:

1. embed câu hỏi;
2. query top-k quiz/question public từ Qdrant;
3. lọc `is_public = true` và `is_deleted = false` trong payload;
4. lấy thêm metadata chi tiết nếu cần từ PostgreSQL;
5. rerank trước khi trả về AI.

## 6. Hybrid retrieval: semantic + SQL

Semantic search không thay thế SQL.

### 6.1 Khi dùng vector

Dùng vector khi user hỏi tự nhiên, mơ hồ, hoặc synonym:

- con vật / động vật / animal;
- kiến thức lớp 6;
- quiz dễ cho trẻ em;
- câu hỏi giống trivia.

### 6.2 Khi dùng SQL

Dùng SQL cho điều kiện rõ ràng:

- quiz public hay private;
- quiz trong tuần này;
- quiz của user nào;
- quiz có hơn 20 câu;
- quiz độ khó hard.

### 6.3 Khi dùng cả hai

Ví dụ:

“Có quiz public nào về con vật, dễ, và có ít nhất 10 câu không?”

Cách xử lý:

- SQL filter: public, dễ, >= 10 câu;
- vector search trên Qdrant: con vật;
- merge kết quả;
- rerank top-k;
- đưa vào prompt.

### 6.4 Top-k ranking nên làm thế nào

Không nên lấy trực tiếp top-k similarity rồi trả thẳng. Nên dùng pipeline 2 bước:

1. Candidate generation

- lấy khoảng 20 đến 50 point từ Qdrant;
- filter theo payload trước;
- giữ lại candidates đủ rộng để tránh bỏ sót.

2. Reranking

- tính điểm cuối dựa trên nhiều tín hiệu;
- ví dụ: vector similarity, public priority, độ khớp tag, số câu hỏi, độ tươi mới, và độ khớp với intent;
- lấy top 3 đến 10 kết quả tốt nhất đưa vào prompt.

Điểm rerank có thể là weighted score, ví dụ:

```text
final_score = 0.60 * vector_score
            + 0.15 * metadata_match
            + 0.15 * freshness_score
            + 0.10 * intent_match
```

Nguyên tắc:

- nếu câu hỏi thiên về ý nghĩa, vector_score chiếm đa số;
- nếu câu hỏi có điều kiện rõ ràng, metadata_match và intent_match tăng trọng số;
- nếu có nhiều candidate gần điểm, ưu tiên dữ liệu public, mới hơn, và phù hợp hơn với câu hỏi.

### 6.5 Trả context vào LLM thế nào

Sau rerank, chỉ đưa một tập context ngắn nhưng chất lượng cao vào prompt:

- 3 đến 5 quiz/question tốt nhất cho query ngắn;
- 5 đến 10 context pieces nếu câu hỏi rộng hơn;
- không nhét toàn bộ top-k vào prompt nếu không cần.

## 7. Text-to-SQL an toàn

Nếu muốn AI query dữ liệu có cấu trúc, không cho sinh SQL tự do.

### 7.1 Cách làm đúng

AI chỉ được chọn intent hoặc tool có sẵn, ví dụ:

- `search_public_quizzes`;
- `get_quiz_details`;
- `search_questions_by_embedding`;
- `get_conversation_messages`;
- `get_friend_list`.

Backend mapping tool này thành query thật.

### 7.2 Không nên làm

- không cho user nhập SQL trực tiếp;
- không cho LLM trả SQL raw rồi execute vô điều kiện;
- không cho query ngoài whitelist bảng/cột.

### 7.3 Dùng text-to-SQL ở đâu

Text-to-SQL hợp nhất cho:

- lọc theo metadata;
- thống kê;
- sort;
- điều kiện kết hợp đơn giản.

Semantic search hợp nhất cho:

- tìm nội dung gần nghĩa;
- tìm quiz/question theo ý định tự nhiên.

## 8. Context của chat AI

### 8.1 Nên lưu thế nào

Khuyến nghị:

- lưu message hiển thị của user và AI chung trong `messages`;
- lưu retrieval context, prompt snapshot, token usage trong `ai_runs` hoặc `metadata` JSONB;
- không nhét toàn bộ prompt thô vào bảng message chính.

### 8.2 Vì sao không nên trộn tất cả vào một bảng chat

Nếu để toàn bộ context AI chung với message, sau này sẽ khó:

- phân biệt message hiển thị với dữ liệu nội bộ;
- audit prompt và token usage;
- đổi model mà không phá schema;
- rerun retrieval khi cần debug;
- dọn retention hoặc privacy rules.

### 8.3 Có thể query dễ hơn không

Có, nếu giữ chung bảng `messages` nhưng tách rõ:

- `sender_type`;
- `metadata`;
- `conversation_id`;
- `message_type` nếu cần.

Đó là cách hợp lý nhất giữa query dễ và mở rộng tốt.

## 9. WebSocket cho social chat + AI

Không nên sửa mạnh vào websocket game hiện tại.

Nên thêm websocket riêng cho social chat, ví dụ:

- `/ws/chat/{conversation_id}`

Flow:

```text
client connect
  -> auth token
  -> check membership
  -> receive user message
  -> save to messages
  -> optionally trigger AI
  -> save AI message
  -> broadcast to members
```

Nếu chạy nhiều backend instance, tiếp tục dùng Redis Pub/Sub nhưng tách channel riêng cho social chat.

## 10. Ingestion pipeline cho quiz public

### 10.1 Khi tạo hoặc sửa quiz

Khi user tạo quiz hoặc sửa câu hỏi:

1. build text representation;
2. tạo embedding;
3. upsert point vào Qdrant;
4. lưu source record chuẩn vào PostgreSQL;
5. cập nhật metadata searchable nếu cần.

### 10.2 Khi quiz đổi trạng thái

Nếu quiz chuyển public/private hoặc bị soft delete:

- cập nhật metadata searchable trong PostgreSQL và payload Qdrant;
- giữ rule `is_public = true` và `is_deleted = false` cho retrieval;
- nếu cần, xóa hoặc vô hiệu hóa point cũ trong Qdrant.

## 11. Query flow cho user hỏi trong chat

Ví dụ người dùng hỏi:

“Có bộ quiz nào liên quan đến con vật không?”

Backend nên làm:

1. lưu message user vào conversation;
2. phân loại intent là search knowledge;
3. tạo embedding cho query;
4. query top-k quiz/question public;
5. lấy vài message gần nhất trong conversation làm ngữ cảnh;
6. ghép kết quả retrieval vào prompt;
7. gọi LLM;
8. lưu AI reply vào messages;
9. broadcast realtime.

Nếu câu hỏi mang tính điều kiện rõ ràng hơn, ví dụ:

“Cho tôi quiz public về con vật, tạo trong tuần này, có hơn 10 câu”

thì backend thêm SQL filter trước rồi mới vector search.

## 12. Kế hoạch triển khai theo phase

### Phase 1

- tạo social tables;
- tạo conversations/messages;
- thêm websocket chat riêng;
- giữ AI chưa bật hoặc trả lời mock.

### Phase 2

- bật embedding cho quiz và question public;
- thêm Qdrant;
- lưu embedding khi quiz/question thay đổi;
- thêm search API top-k và reranking.

### Phase 3

- thêm intent router;
- thêm safe text-to-SQL / tool calling;
- kết hợp semantic search với SQL filter;
- lưu `ai_runs` để audit.

### Phase 4

- tối ưu hybrid retrieval;
- thêm ranking lại kết quả;
- thêm caching cho query phổ biến;
- thêm monitoring cho latency và token usage.

## 13. Nguyên tắc thiết kế

- chỉ dùng `users` làm gốc định danh;
- tách game chat và social chat;
- không cho LLM tự execute SQL raw;
- public data phải được lọc rõ;
- AI chỉ trả lời dựa trên conversation hiện tại + quiz public + metadata được phép;
- lưu audit đủ để debug nhưng không làm bẩn bảng hiển thị.

## 14. Kết luận

Kiến trúc phù hợp nhất cho Quiz Battle là hybrid RAG:

- semantic search cho quiz/question;
- SQL cho metadata và điều kiện;
- text-to-SQL có kiểm soát để gọi dữ liệu có cấu trúc;
- WebSocket riêng cho social chat;
- `users` là gốc duy nhất cho danh tính;
- AI context được lưu riêng nhưng vẫn query dễ qua `conversation_id`.

Nếu làm theo lộ trình này, hệ thống sẽ mở rộng được từ quiz app sang một mạng xã hội thu nhỏ có AI trợ lý chat mà vẫn giữ schema sạch và dễ bảo trì.

## 15. AI server riêng: chạy ở đâu, như nào, và model gì

Để tránh làm nặng backend FastAPI hiện tại, nên tách AI inference thành một service riêng. Service này chỉ nhận nhiệm vụ:

- nhận prompt đã được backend ghép sẵn;
- truy vấn retrieval nếu cần;
- chạy inference model;
- trả kết quả về backend chính.

### 15.1 AI server nên chạy ở đâu

Trong kiến trúc local bằng Docker Compose, AI server nên là một container riêng, ngang hàng với backend, db và redis.

Luồng đề xuất:

```text
frontend -> backend FastAPI -> ai-server -> backend FastAPI -> frontend
```

Backend chính vẫn là nơi:

- xác thực người dùng;
- kiểm tra quyền truy cập conversation;
- lấy context chat;
- lấy dữ liệu quiz public;
- gọi AI server.

AI server cũng có thể truy cập trực tiếp PostgreSQL qua network nội bộ Docker để đọc dữ liệu phục vụ RAG, thay vì bắt buộc đi qua backend.

Mô hình phù hợp cho cách này là:

- backend vẫn giữ auth, policy, và websocket broadcast;
- AI server đọc trực tiếp dữ liệu cần thiết từ DB để lấy quiz/question/public metadata;
- nếu cần write, chỉ write các bản ghi nội bộ như `ai_runs` hoặc log kỹ thuật;
- quyền DB nên tách riêng bằng user chỉ-đọc cho retrieval và user riêng cho audit/write nếu thật sự cần.

Điều này giúp giảm một lớp trung gian khi query RAG, nhưng vẫn giữ backend chính là nơi kiểm soát quyền truy cập cuối cùng.

### 15.2 AI server nên làm gì

AI server nên có 3 lớp chức năng:

1. Inference layer

- chạy model đã quantize 4-bit;
- hỗ trợ streaming nếu cần;
- trả response theo token hoặc theo chunk.

2. Embedding layer

- tạo embedding cho quiz, question, và query của người dùng;
- ưu tiên chạy trên GPU nếu pipeline embedding hỗ trợ;
- lưu vector về Qdrant hoặc vector store nội bộ.

3. Prompt orchestration layer

- nhận context từ backend;
- ghép system prompt, chat history, retrieval results;
- giới hạn độ dài context;
- trả prompt đã sẵn sàng cho model.

4. Model routing layer

- chọn model theo tác vụ;
- ví dụ chat ngắn, QA, summarization;
- sau này có thể thêm model khác nhưng vẫn giữ chung giao diện API.

### 15.3 Mô hình nên dùng

Yêu cầu của bài toán là mô hình nhẹ, tầm 2B-3B tham số, chạy 4-bit quantization trên llama.cpp đã build GPU.

Các lựa chọn hợp lý:

- Qwen2.5-3B-Instruct GGUF 4-bit;
- Llama 3.2 3B Instruct GGUF 4-bit;
- Phi-3 Mini Instruct nếu muốn nhỏ hơn, nhưng vẫn nên ưu tiên model có khả năng tiếng Anh tốt và suy luận ổn.

Khuyến nghị thực dụng nhất:

- ưu tiên Qwen2.5-3B-Instruct 4-bit nếu cần cân bằng tốt giữa chất lượng và tài nguyên;
- nếu GPU rất hạn chế, có thể hạ xuống model nhỏ hơn nhưng chất lượng trả lời cho RAG sẽ giảm.

Lý do chọn nhóm model này:

- đủ nhẹ để chạy local;
- đủ tốt cho chat + retrieval + tóm tắt;
- đủ linh hoạt để trả lời theo context của conversation;
- dễ chạy trên llama.cpp dạng GGUF.

### 15.4 Runtime khuyến nghị

AI server nên được build theo kiểu:

- llama.cpp đã compile với GPU support;
- model file `.gguf` 4-bit;
- server expose HTTP API nội bộ, ví dụ `/generate`, `/embed`, `/health`;
- nếu sau này cần embedding riêng, có thể chạy chung binary hoặc tách thành service embedding độc lập.

Với yêu cầu này, inference và embedding nên được đẩy tối đa lên GPU VRAM:

- LLM inference chạy qua llama.cpp GPU backend;
- embedding model cũng nên chạy GPU nếu dùng cùng runtime hoặc cùng một inference stack;
- phần CPU/RAM trên container chỉ nên giữ cho orchestration, tokenization, I/O, network, và bookkeeping nhẹ;
- không nên để backend chính làm inference hay embedding.

Nói cách khác, WSL Ubuntu của Docker chỉ đóng vai trò môi trường chạy container, còn phần nặng của mô hình phải nằm trên GPU VRAM.

Runtime flow gợi ý:

```text
ai-server
  -> đọc DB trực tiếp để lấy quiz/question/public metadata khi cần
  -> embed query hoặc retrieval chunk trên GPU
  -> query Qdrant top-k
  -> rerank candidates
  -> chạy llama.cpp GPU cho inference
  -> trả text hoặc streaming tokens
```

### 15.5 Dockerfile của AI server trong tương lai

Khi triển khai thật, AI server nên có Dockerfile riêng với các bước sau:

1. base image phù hợp với CUDA hoặc runtime GPU hiện có;
2. build llama.cpp với GPU backend;
3. copy model `.gguf` vào container hoặc mount volume model riêng;
4. expose port nội bộ cho inference API;
5. set healthcheck để backend biết service đã sẵn sàng.

Tài liệu này chỉ mô tả hướng, chưa chỉnh Dockerfile thật.

### 15.6 docker-compose.yml trong tương lai

Sau này docker-compose nên thêm một service riêng, ví dụ `ai-server`, với các ý chính:

- `build` từ Dockerfile riêng;
- mount volume chứa model GGUF;
- expose cổng nội bộ cho backend;
- connect thẳng tới PostgreSQL trong network nội bộ Docker để query dữ liệu RAG;
- connect tới Qdrant trong network nội bộ Docker để search vector;
- phụ thuộc vào GPU runtime nếu chạy local hoặc trên máy có CUDA;
- đặt biến môi trường cho model name, context size, number of threads, GPU layers.

Các biến môi trường nên có thêm:

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` cho read-only hoặc audit access;
- `QDRANT_URL`, `QDRANT_API_KEY` nếu bật auth;
- `MODEL_PATH` cho file GGUF;
- `GPU_LAYERS` hoặc biến tương đương để đẩy nhiều layer nhất có thể lên VRAM;
- `CONTEXT_SIZE`, `BATCH_SIZE`, `THREADS` cho tuning;
- `EMBEDDING_MODEL` nếu tách model embedding riêng.

Ý nghĩa của service này:

- backend gọi AI server qua mạng nội bộ Docker khi cần orchestration;
- frontend không gọi trực tiếp AI server;
- AI server có thể tự query DB và Qdrant cho retrieval, nhưng auth và policy cuối cùng vẫn nằm ở backend chính;
- inference và embedding nên ưu tiên VRAM, không để backend chính gánh CPU/RAM cho phần nặng.

### 15.7 API contract giữa backend và AI server

Nên thống nhất sớm format request/response để sau này thay model không phải sửa nhiều.

Ví dụ request:

```json
{
  "conversation_id": "...",
  "user_message": "...",
  "history": [],
  "retrieved_context": [],
  "mode": "rag_chat"
}
```

Ví dụ response:

```json
{
  "answer": "...",
  "citations": [],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0
  }
}
```

### 15.8 Kết luận cho phần AI server

Nếu muốn hệ thống bền và dễ mở rộng, nên tách AI inference ra khỏi backend FastAPI ngay từ kiến trúc. Backend chính chỉ làm orchestration và quyền truy cập, còn AI server chạy llama.cpp GPU với model 2B-3B 4-bit, ví dụ Qwen2.5-3B-Instruct hoặc Llama 3.2 3B Instruct.

Trong giai đoạn này, chỉ cần ghi thiết kế trong RAG.md. Khi bắt tay vào code, mới thêm Dockerfile và docker-compose service riêng.

## 16. Qdrant collection layout khuyến nghị

Để dễ vận hành và dễ mở rộng, nên chia vector data theo collection theo domain thay vì nhét mọi thứ vào một collection lớn.

### 16.1 Collection đề xuất

- `quiz_embeddings`
  - chứa embedding của cả quiz;
  - dùng cho search theo chủ đề quiz;
  - mỗi point map về một quiz gốc.

- `question_embeddings`
  - chứa embedding của từng câu hỏi;
  - dùng khi user hỏi sát nội dung;
  - mỗi point map về một question gốc.

- `retrieval_chunks`
  - chứa chunk nhỏ từ mô tả dài, rule, hướng dẫn, hoặc nội dung đã tách nhỏ;
  - dùng khi nội dung quá dài để nhét vào một point.

- `chat_context_embeddings`
  - chứa embedding của lịch sử chat đã được chọn lọc;
  - dùng sau này nếu muốn recall các mẩu đối thoại cũ theo ngữ nghĩa.

### 16.2 Payload chuẩn

Mỗi point nên có payload tối thiểu:

- `source_type`
- `source_id`
- `quiz_id`
- `conversation_id` nếu liên quan chat;
- `is_public`
- `is_deleted`
- `tag`
- `difficulty`
- `chunk_index`
- `updated_at`

Payload này giúp Qdrant filter nhanh trước khi rerank.

### 16.3 Quy tắc upsert

Khi dữ liệu gốc thay đổi:

1. cập nhật PostgreSQL trước;
2. regenerate embedding nếu nội dung text thay đổi;
3. upsert point mới vào Qdrant bằng cùng `source_id`;
4. xóa point cũ nếu record bị xóa mềm hoặc không còn public.

Nguyên tắc là PostgreSQL vẫn là nguồn sự thật, Qdrant là tầng truy xuất.

## 17. Ranking top-k hợp lý

### 17.1 Không dùng similarity thô một mình

Không nên lấy top-k trả thẳng theo vector similarity vì kết quả có thể:

- quá thiên về một từ khóa;
- bỏ sót dữ liệu public tốt hơn nhưng điểm vector thấp hơn chút;
- không ưu tiên dữ liệu mới hoặc đúng intent.

### 17.2 Pipeline khuyến nghị

Retrieval nên đi theo 2 bước:

1. Candidate generation

- query Qdrant lấy 20 đến 50 candidates;
- filter payload trước;
- giữ tập ứng viên đủ rộng.

2. Reranking

- tính điểm cuối theo nhiều tín hiệu;
- chọn top 3 đến 10 item tốt nhất;
- đưa vào prompt hoặc trả về UI.

### 17.3 Công thức score gợi ý

```text
final_score = 0.55 * vector_score
            + 0.20 * metadata_match
            + 0.10 * freshness_score
            + 0.10 * intent_match
            + 0.05 * popularity_score
```

Giải thích:

- `vector_score`: mức độ gần nghĩa của query với content;
- `metadata_match`: khớp public/private, difficulty, tag, số câu;
- `freshness_score`: ưu tiên content mới hoặc vừa cập nhật;
- `intent_match`: khớp intent người dùng đang hỏi;
- `popularity_score`: tùy chọn, dùng nếu có dữ liệu tương tác.

### 17.4 Quy tắc xếp hạng theo loại câu hỏi

- Nếu user hỏi mở, thiên về chủ đề: ưu tiên `vector_score`.
- Nếu user hỏi có điều kiện rõ: ưu tiên `metadata_match` và `intent_match`.
- Nếu user hỏi quiz public hay private: filter trước, rồi rerank.
- Nếu user hỏi về một chủ đề rất rộng: lấy nhiều candidates hơn, sau đó shrink xuống top nhỏ hơn.

### 17.5 Output cuối cho LLM

Sau rerank, chỉ nên đưa vào prompt:

- 3 đến 5 item cho query hẹp;
- 5 đến 10 item cho query rộng;
- mỗi item kèm title, short summary, và một vài metadata quan trọng;
- không đưa toàn bộ payload thô nếu không cần.

## 18. Lộ trình triển khai thực tế

### Phase A: nền tảng social + RAG

- tạo social tables chỉ FK về `users`;
- tạo `conversations`, `conversation_members`, `messages`;
- tách websocket social chat ra khỏi websocket game;
- giữ AI server ở mức mô phỏng hoặc trả lời mock.

### Phase B: Qdrant + embedding

- dựng Qdrant service riêng;
- tạo collection cho quiz và question;
- upsert embedding khi quiz/question thay đổi;
- lấy query embedding từ AI server;
- search top-k trong Qdrant.

### Phase C: ranking + prompt orchestration

- thêm rerank layer;
- thêm prompt assembler;
- thêm `ai_runs` để audit;
- giới hạn context length và top-k đưa vào prompt.

### Phase D: GPU AI server

- build llama.cpp với GPU backend;
- mount model GGUF 4-bit;
- expose `/generate`, `/embed`, `/health`;
- cho AI server đọc trực tiếp PostgreSQL và Qdrant;
- tối ưu `GPU_LAYERS`, `BATCH_SIZE`, `CONTEXT_SIZE`.

## 19. Checklist triển khai nhanh

Khi bắt đầu code, nên theo thứ tự:

1. Chốt schema social chat.
2. Chốt schema audit và AI run log.
3. Dựng Qdrant collection và payload chuẩn.
4. Viết embedding pipeline cho quiz/question.
5. Viết search + rerank service.
6. Dựng AI server riêng trên GPU.
7. Nối backend với AI server qua API nội bộ.
8. Bật chat AI trong conversation.
9. Theo dõi latency, token usage, và chất lượng retrieval.

## 20. Kết luận cuối

Kiến trúc mục tiêu cho Quiz Battle nên là:

- PostgreSQL giữ dữ liệu nghiệp vụ và audit;
- Qdrant giữ vector và hỗ trợ retrieval;
- AI server riêng chạy llama.cpp GPU để inference và embedding;
- backend chính giữ auth, policy, websocket, và orchestration;
- retrieval dùng top-k + rerank thay vì similarity thô.

Nếu đi theo cấu trúc này, hệ thống sẽ đủ sạch để mở rộng từ quiz app thành mạng xã hội nhỏ có AI chat, mà vẫn giữ được khả năng query nhanh, tách lớp rõ, và dễ bảo trì.

## 21. Issues to Resolve: Ollama Migration & GPU Optimization

### 21.1 Issue 1: Thay llama.cpp bằng Ollama

**Vấn đề hiện tại:**
Thiết kế hiện tại đề xuất dùng llama.cpp với GPU backend. Tuy nhiên, Ollama là giải pháp tốt hơn vì:

- Ollama cung cấp HTTP API sẵn sàng, không cần build từ source;
- Ollama tự động quản lý model download, quantization, và cache;
- Ollama hỗ trợ multiple models cùng lúc trong memory;
- Ollama có UI tích hợp để monitor và debug;
- Ollama đã tối ưu GPU inference cho các model phổ biến.

**Yêu cầu:**

1. Thay llama.cpp bằng Ollama trong AI server;
2. Config Ollama pull model GGUF từ Ollama library (e.g., `qwen2.5:3b-instruct-q4_0`);
3. Update Dockerfile để chạy Ollama container riêng hoặc chạy Ollama service bên trong AI server container;
4. Update docker-compose.yml để expose Ollama API port;
5. Update AI server endpoints từ llama.cpp API sang Ollama `/api/generate` và `/api/embed`;
6. Kiểm chứng compatibility giữa Ollama embedding models và Qdrant;
7. Viết tài liệu cách setup Ollama local cho development.

**Lợi ích:**

- giảm complexity khi build và maintain llama.cpp binary;
- dễ thay model mà không rebuild container;
- community support tốt hơn;
- deployment nhanh hơn.

### 21.2 Issue 2: Tối ưu GPU/VRAM cho LLM inference và embedding

**Vấn đề hiện tại:**
Thiết kế đề cập đẩy layer tính toán lên GPU, nhưng chưa rõ cách thực thi cụ thể từng bước.

**Yêu cầu:**

1. **LLM inference tối ưu:**
   - Đẩy toàn bộ model weights lên VRAM (GPU layers = model size);
   - Config batch size phù hợp với VRAM còn lại;
   - Dùng Flash Attention hay attention optimization nếu model support;
   - Giữ CPU/system RAM chỉ cho tokenizer, logits processing, và I/O;
   - Monitor VRAM usage để tránh OOM.

2. **Embedding inference tối ưu:**
   - Nếu dùng riêng embedding model (e.g., `nomic-embed-text`), đẩy hết lên GPU;
   - Nếu dùng embedding layer của LLM chính, ensure layer đó cũng chạy GPU;
   - Batch embedding requests nếu có để maximize GPU utilization;
   - Cache embedding output nếu query lặp lại.

3. **Config cụ thể:**
   - Ollama: set `OLLAMA_GPU=1` hoặc tương đương cho enable GPU;
   - Ollama: test `GPU_LAYERS` parameter để đẩy hết model lên VRAM;
   - docker-compose: mount `--gpus all` hoặc specific GPU devices;
   - Dockerfile: base image phù hợp với NVIDIA CUDA (e.g., `nvidia/cuda:12.2-runtime`);
   - Environment variables: `CUDA_VISIBLE_DEVICES`, `OLLAMA_NUM_GPU`, `OLLAMA_LOAD_TIMEOUT`.

4. **Benchmark & monitoring:**
   - Đo latency inference trước/sau optimization;
   - Đo VRAM peak usage;
   - Đo throughput (tokens/second);
   - Kiểm tra có GPU memory leak không;
   - Log khi model được load/unload.

5. **Test edge cases:**
   - Parallel requests từ multiple conversations;
   - Rapid embedding requests khi indexing quiz/question;
   - Long context prompts (2K-4K tokens);
   - CPU fallback nếu GPU full hoặc error.

**Lợi ích:**

- Inference speed tăng 5-10x so với CPU-only;
- Embedding tạo nhanh hơn khi reindexing;
- Giảm latency chat response từ vài giây xuống ~1 giây;
- Hệ thống đủ khả năng chạy model lớn hơn (7B) nếu VRAM cho phép.

### 21.3 Implementation approach: Social Chat First, Ollama Microservice Second

**Priority 1: Social Chat Foundation**

Build phần social chat trước, gồm:

- Social data models: `friendships`, `conversations`, `conversation_members`, `messages`;
- WebSocket endpoint `/ws/chat/{conversation_id}` riêng biệt khỏi game chat;
- Message API: create, list, edit, delete;
- Real-time broadcast qua Redis Pub/Sub;
- No AI integration yet (mock response hoặc skip AI).

Điều này cho phép:

- User có thể chat với nhau ngay;
- Backend architecture đã sẵn sàng cho AI sau;
- Kiểm soát scope rõ ràng, dễ test.

**Priority 2: Ollama Microservice (Separate, Independent)**

Sau khi social chat stable, thêm Ollama microservice riêng:

- Docker container chạy Ollama độc lập;
- HTTP API endpoint nội bộ, ví dụ `http://ollama:11434`;
- Không modify backend FastAPI cơ bản, chỉ thêm API call khi AI được bật;
- Dễ deploy, scale, hoặc replace model mà không ảnh hưởng social chat.

Flow sau này:

```text
frontend -> backend FastAPI -> [conversations, messages] -> Ollama microservice -> response
```

Backend chỉ gọi Ollama khi user bật AI, không phụ thuộc vào nó.

### 21.4 Timeline

- **Phase 1 (Now):** Build social chat tables, API, WebSocket;
- **Phase 2 (After Phase 1 stable):** Add Qdrant + embedding pipeline;
- **Phase 3 (Later):** Spin up Ollama microservice, integrate AI endpoints;
- **Phase 4 (Final):** GPU optimization, reranking, monitoring.

## 22. Issue mới: Chuyển từ Ollama / local GPU sang Gemini API qua proxy bên thứ 3

> **Trạng thái:** Đề xuất (chưa implement). Xem chi tiết triển khai ở file `PHASE3_GEMINI_MIGRATION.md`.

### 22.1 Bối cảnh

Thiết kế AI server hiện tại (mục 15 và 21) dựa trên:

- Ollama chạy local (Docker container riêng) với model GGUF 2B-3B 4-bit;
- embedding model local như `multilingual-e5-small` hoặc `nomic-embed-text`;
- toàn bộ inference và embedding chạy trên GPU local của dev (WSL/CUDA).

Hướng này gặp một số vấn đề thực tế:

- máy dev không phải lúc nào cũng có GPU rảnh, hoặc GPU VRAM không đủ cho cả LLM 3B + embedding;
- Ollama local chậm hơn nhiều so với API hosted (ví dụ Gemini 2.5 Flash) về tốc độ phản hồi;
- khi làm việc trên nhiều máy (laptop cơ quan, laptop cá nhân, server test), mỗi nơi phải setup lại Ollama, model cache, GPU driver;
- debug latency, tải model, OOM tốn thời gian hơn là tập trung vào logic RAG;
- muốn thử nhanh nhiều model lớn hơn (Gemini 2.5 Flash, Pro) mà local không kham nổi.

Vì vậy cần một hướng mới: dùng **Gemini API thông qua proxy bên thứ 3** thay vì tự host Ollama.

### 22.2 Mục tiêu mới

- LLM chat: dùng `gemini-2.5-flash` qua proxy `https://api.shopaikey.com/v1`.
- Embedding: dùng `gemini-embedding-001` qua cùng proxy đó.
- Bỏ hoàn toàn Ollama container, bỏ model GGUF local, bỏ phần GPU/VRAM tuning.
- Bỏ luôn local embedding model (sentence-transformers / fastembed) trong backend.
- Code AI orchestration nằm gọn trong backend FastAPI, gọi HTTP ra ngoài, không cần microservice riêng.

### 22.3 Tác động lên kiến trúc đã vạch ra

Mục 15 và 21 mô tả AI server riêng chạy Ollama + llama.cpp. Với hướng Gemini proxy:

- Không cần `ai-server` container trong `docker-compose.yml`.
- Không cần Dockerfile cho AI server.
- Không cần biến `MODEL_PATH`, `GPU_LAYERS`, `CONTEXT_SIZE`, `THREADS`, `BATCH_SIZE`.
- Không cần mount volume chứa GGUF model.
- Không cần healthcheck cho AI server.

Thay vào đó backend chỉ cần:

- một HTTP client (`httpx`) gọi tới `https://api.shopaikey.com/v1/chat/completions` cho LLM;
- một HTTP client gọi tới `https://api.shopaikey.com/v1/embeddings` cho embedding;
- biến môi trường `GEMINI_PROXY_BASE_URL` và `GEMINI_PROXY_API_KEY`;
- biến `LLM_MODEL` (mặc định `gemini-2.5-flash`) và `EMBEDDING_MODEL` (mặc định `gemini-embedding-001`).

### 22.4 Tác động lên Qdrant và retrieval

Vector size thay đổi khi đổi embedding model:

- `multilingual-e5-small` (local, cũ): 384 dim.
- `gemini-embedding-001` (mới, qua proxy): 3072 dim.

Hệ quả:

- Phải cập nhật `QDRANT_VECTOR_SIZE` trong config khớp với dim của `gemini-embedding-001`.
- Phải drop 4 collection cũ (vector size 384) và tạo lại với vector size mới.
- Phải chạy lại `backfill_embeddings.py` để re-index toàn bộ quiz/question bằng embedding mới.
- Bỏ luôn logic E5 prefix (`passage: ` / `query: `) vì Gemini embedding không cần prefix đó.

Các task liên quan sẽ được mô tả chi tiết trong `PHASE3_GEMINI_MIGRATION.md`.

### 22.5 Tác động lên RAG prompt

- Vẫn giữ cấu trúc RAG: retrieve top-k từ Qdrant → ghép context → gọi LLM → lưu message AI.
- Có thể tăng `top_k` lên một chút (ví dụ 8-12) vì LLM giờ mạnh hơn, context window lớn hơn.
- System prompt có thể bổ sung rằng model là `gemini-2.5-flash` để audit trong `ai_runs`.
- Theo dõi `usage.prompt_tokens` và `usage.completion_tokens` từ response của proxy.

### 22.6 Tác động lên `ai_runs`

Bảng `ai_runs` (mục 4.3) nên lưu thêm:

- `model_name`: cố định là `gemini-2.5-flash` (hoặc override qua env);
- `embedding_model`: `gemini-embedding-001`;
- `embedding_dim`: 3072 (hoặc giá trị cấu hình);
- `provider`: `gemini-proxy`;
- `proxy_base_url`: log lại base URL (che bớt phần secret nếu cần).

### 22.7 Lợi ích

- Không phụ thuộc GPU local, có thể dev trên máy yếu hoặc trên cloud editor.
- Tốc độ phản hồi chat nhanh hơn đáng kể so với model 2-3B local.
- Dễ đổi model (đổi env var), không cần rebuild image.
- Không phải quản lý Ollama cache, model versioning, GPU driver.
- Chi phí dev/test thấp nếu proxy free tier hoặc rẻ.

### 22.7 Rủi ro và biện pháp giảm thiểu

- **Phụ thuộc mạng:** backend cần internet ra ngoài proxy. Có retry + timeout hợp lý, có fallback message thân thiện khi không gọi được.
- **Rate limit / quota:** proxy có thể giới hạn request/giây hoặc quota ngày. Cần log `usage`, cảnh báo khi gần quota.
- **Bảo mật API key:** key lưu trong `.env` (không commit), trong production dùng secret manager.
- **Vendor lock-in:** dùng OpenAI-compatible schema của proxy (`/chat/completions`, `/embeddings`) để sau này đổi provider chỉ tốn đổi base URL + model name, không phải sửa logic service.
- **Data privacy:** dữ liệu quiz và câu hỏi user gửi sang proxy bên thứ 3. Nên tránh gửi PII (email, username) trong prompt nếu không cần.

### 22.8 Phạm vi thay đổi

Các file chính sẽ bị ảnh hưởng (chưa sửa, liệt kê để theo dõi):

- `backend/app/core/config.py` — thêm `LLM_*`, `EMBEDDING_*`, `GEMINI_PROXY_*`.
- `backend/app/services/embedding_service.py` — thay sentence-transformers bằng HTTP call.
- `backend/app/services/llm_service.py` — **mới**, gọi proxy `/chat/completions`.
- `backend/app/services/ingestion_service.py` — chỉnh phần text builder (bỏ prefix E5).
- `backend/app/services/qdrant_service.py` — chỉnh vector size.
- `backend/scripts/backfill_embeddings.py` — chạy lại với embedding mới.
- `backend/app/main.py` — bỏ warmup model local, thêm health check proxy.
- `backend/requirements.txt` — bỏ `sentence-transformers`, `qdrant-client[fastembed]` vẫn giữ, thêm `httpx` (đã có).
- `docker-compose.yml` — bỏ `ai-server` service nếu có.
- Tài liệu: `RAG.md` (mục này), `PHASE2_SETUP.md` (cập nhật), `PHASE3_GEMINI_MIGRATION.md` (mới, chi tiết).
- `.env.example` — thêm các biến Gemini proxy.

### 22.9 Không thay đổi

- Kiến trúc tổng thể của RAG (retrieve → rerank → prompt → LLM).
- Schema `conversations`, `messages`, `ai_runs` (chỉ thêm cột phụ cho audit).
- WebSocket realtime cho chat game và chat social.
- Phần auth, policy, RBAC của backend.
- Cấu trúc payload Qdrant (`source_type`, `source_id`, `is_public`, `is_deleted`, ...).
