#

GIAI ĐOẠN 1: CƠ SỞ DỮ LIỆU & QUẢN LÝ QUIZ (NỀN TẢNG)
Mục tiêu: Giúp Frontend thoát khỏi dữ liệu ảo khi tạo và hiển thị Quiz.

Task 1: Migration & Schema Update

Cập nhật bảng game_rooms với các settings (max_players, chat_enabled...).

Cập nhật bảng quizzes (category, difficulty, play_count...).

Đảm bảo tất cả bảng có created_at và updated_at.

Task 2: API CRUD Quiz nâng cao

Viết Logic xử lý Transaction cho POST /quizzes (Tạo Quiz + Questions + Options cùng lúc).

Viết GET /quizzes/{id} trả về full cấu trúc lồng nhau (Nested JSON).

Cài đặt API Duplicate quiz.

Task 3: Integration Editor Screen (FE)

Thay thế state demo bằng API call.

Validate dữ liệu đầu vào (ít nhất 1 câu hỏi, đúng 1 đáp án đúng).

GIAI ĐOẠN 2: DASHBOARD & QUẢN LÝ PHÒNG CHỜ (LOBBY)
Mục tiêu: Kết nối người chơi với nhau và hiển thị thông số cá nhân.

Task 4: API Dashboard & User Stats

Viết API GET /dashboard tổng hợp (Stats + Recent Quizzes).

Viết API GET /users/me/stats tính toán từ bảng user_stats.

Task 5: Logic Create & Join Room

POST /rooms: Sinh mã room_code ngẫu nhiên/duy nhất, tự động thêm Host vào danh sách player.

POST /rooms/{code}/join: Kiểm tra slot trống, trạng thái phòng.

Task 6: Lobby Synchronization (Rest API)

API lấy danh sách player trong phòng.

API Chat (Lưu và tải tin nhắn cũ).

GIAI ĐOẠN 3: REALTIME CORE (WEBSOCKET & DÒNG CHẢY GAME)
Mục tiêu: Chuyển đổi từ request-response sang sự kiện thời gian thực.

Task 7: Setup WebSocket Server (FastAPI)

Xây dựng ConnectionManager để quản lý các socket theo room_code.

Middleware xác thực Token qua URL query string.

Task 8: WebSocket Service (Frontend)

Chuyển từ socket.io-client sang native WebSocket.

Viết hàm xử lý dispatch event (PLAYER_JOINED, PLAYER_LEFT).

Task 9: Game Flow Control

POST /rooms/{code}/start: Khởi tạo game_questions từ Quiz gốc.

Phát event GAME_STARTED qua WS để FE tự động chuyển màn hình Gameplay.

GIAI ĐOẠN 4: GAMEPLAY & LOGIC TÍNH ĐIỂM
Mục tiêu: Xử lý tương tác chính trong trò chơi.

Task 10: Answer Submission & Validation

API POST /answers: Kiểm tra đáp án đúng/sai, tính điểm dựa trên thời gian trả lời.

Ghi đè/Chặn nếu user trả lời lại cùng một câu.

Task 11: Realtime Leaderboard

Mỗi khi có người trả lời, tính toán lại hạng và phát event LEADERBOARD_UPDATED.

Task 12: Question Transition

API next-question: Chỉ Host được gọi, thay đổi current_question_order và phát event QUESTION_CHANGED.

GIAI ĐOẠN 5: KẾT THÚC & TỔNG KẾT (RESULT & CLEANUP)
Mục tiêu: Lưu trữ kết quả cuối cùng và dọn dẹp tài nguyên.

Task 13: Game Finish Logic

API finish: Tổng hợp từ player_answers vào game_results.

Cập nhật play_count cho Quiz và total_score cho User Profile.

Task 14: Result Screen Integration

FE gọi API results để hiển thị Podium (Top 3) và bảng điểm chi tiết của cá nhân.

Task 15: Room Cleanup

Đóng kết nối WS, chuyển trạng thái room về FINISHED hoặc xóa room tạm.

TÓM TẮT KIẾN TRÚC LUỒNG DỮ LIỆU
Lời khuyên cho Vinh:

Alembic: Bạn hãy dùng Alembic ngay từ Task 1 để quản lý version DB, vì trong quá trình làm gameplay chắc chắn sẽ phát sinh thêm cột.

Authentication: Vì dùng native WS, đừng quên truyền token qua URL (ví dụ: ws://.../ws/game/123?token=abc) vì WS không gửi được Custom Header như REST.

Logging: Khi làm Realtime, hãy log kỹ các event type để biết BE đã phát đi mà FE chưa nhận được hay do logic FE xử lý sai.

GIAI ĐOẠN 6: MIGRATE AI SANG GEMINI API QUA PROXY (THAY LOCAL GPU)
Mục tiêu: Bỏ hoàn toàn Ollama / local embedding model, dùng Gemini API qua proxy bên thứ 3 https://api.shopaikey.com/v1.

Xem chi tiết kỹ thuật ở file PHASE3_GEMINI_MIGRATION.md, tóm tắt kiến trúc ở RAG.md mục 22.

Task 16: Cấu hình biến môi trường cho Gemini proxy

- Thêm GEMINI_PROXY_BASE_URL, GEMINI_PROXY_API_KEY, LLM_MODEL, EMBEDDING_MODEL, EMBEDDING_DIM, QDRANT_VECTOR_SIZE vào backend/.env và .env.example.
- Cập nhật app/core/config.py với các field mới (giữ backward compatible nếu cần).
- Bỏ hoặc comment các biến cũ liên quan tới local embedding/Ollama.

Task 17: Rewrite embedding_service dùng Gemini embedding qua proxy

- Bỏ import sentence-transformers.
- Bỏ hàm get_embedder(), bỏ logic prefix passage:/query:.
- Triển khai embed_passages() và embed_query() qua httpx, gọi POST {GEMINI_PROXY_BASE_URL}/embeddings.
- Hỗ trợ batch embedding để giảm số request khi backfill.
- Giữ nguyên chữ ký hàm để ingestion_service và search_service không phải sửa.

Task 18: Tạo llm_service mới gọi Gemini qua proxy

- Tạo app/services/llm_service.py.
- Triển khai chat_completion() (sync hoặc async) gọi POST {GEMINI_PROXY_BASE_URL}/chat/completions với model gemini-2.5-flash.
- Hỗ trợ system prompt + user message + chat history.
- Trả về answer text + usage (prompt_tokens, completion_tokens).
- Xử lý timeout, retry, và fallback message khi proxy lỗi.

Task 19: Cập nhật Qdrant collection cho vector size mới

- Đổi QDRANT_VECTOR_SIZE từ 384 sang 768 (theo EMBEDDING_DIM).
- Drop 4 collection cũ trong Qdrant.
- Restart backend để ensure_collections() tạo lại với dim mới.
- Verify payload schema không đổi.

Task 20: Chạy lại backfill_embeddings

- Cập nhật scripts/backfill_embeddings.py nếu cần (signature không đổi nhờ Task 17).
- Chạy backfill toàn bộ quiz public còn lại trong PostgreSQL.
- Verify số point trong collection khớp với số quiz/question active.
- Test retrieval với query tiếng Việt và tiếng Anh.

Task 21: Cập nhật requirements.txt và docker-compose

- Bỏ sentence-transformers khỏi requirements.txt.
- Giữ qdrant-client (vẫn cần), httpx (đã có).
- Bỏ (hoặc không thêm) service ai-server/Ollama trong docker-compose.yml.
- Không mount model cache volume.

Task 22: Cập nhật tài liệu

- Cập nhật PHASE2_SETUP.md phần Migration Note (đã có).
- Đảm bảo RAG.md mục 22 khớp với implementation thực tế.
- Cập nhật README nếu có đề cập tới Ollama / local model.
- Viết Troubleshooting cho Gemini proxy: timeout, rate limit, key invalid, model not found.
