# Quiz Battle - Hướng dẫn chạy bằng Docker Compose

## Yêu cầu
- Docker Desktop / Docker Engine + Docker Compose v2+
- API key Gemini proxy (lấy từ https://api.shopaikey.com/)

## Bước 1: Tạo file `.env` ở thư mục GỐC dự án (ngang hàng với `docker-compose.yml`)

```bash
# Từ thư mục gốc
cp env-docker-template.txt .env
# Rồi sửa .env, điền các giá trị thật:
#   - GEMINI_PROXY_API_KEY
#   - SECRET_KEY (random mạnh)
#   - GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (nếu dùng)
#   - SMTP_* (nếu dùng email OTP)
```

Các biến quan trọng cần điền trong `.env`:

```bash
SECRET_KEY=<random-strong-secret>
GEMINI_PROXY_API_KEY=<api-key-thật-của-bạn>
# optional:
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...
# SMTP_USERNAME=...
# SMTP_PASSWORD=...
```

## Bước 2: Khởi động toàn bộ stack

```bash
docker compose up -d --build
```

Lần đầu sẽ:
- Pull image `postgres:15-alpine`, `redis:7-alpine`, `qdrant/qdrant:v1.9.0`, `pgadmin4`, `redisinsight`
- Build image `backend` (từ `backend/Dockerfile`, cài `qdrant-client` từ `requirements.txt`)
- Build image `frontend` (từ `frontend/Dockerfile`)

## Bước 3: Xem log backend để verify

```bash
docker compose logs -f backend
```

Phải thấy các dòng:

```
✅ Database tables created successfully!
✅ Quiz soft-delete columns verified!
✅ Alembic migrations completed!
✅ Qdrant collections ready!
✅ Gemini proxy API key configured.
✅ Redis Pub/Sub listener started!
```

## Bước 4: Mở các UI

| Service | URL | Ghi chú |
|---------|-----|---------|
| Frontend (Next.js) | http://localhost:3000 | App chính |
| Backend Swagger | http://localhost:8000/docs | API docs + test |
| Backend health | http://localhost:8000/health | Sanity check |
| Qdrant dashboard | http://localhost:6333/dashboard | Vector DB inspect |
| pgAdmin | http://localhost:5050 | Email: `${PGADMIN_DEFAULT_EMAIL:-admin@example.com}`, Pass: `${PGADMIN_DEFAULT_PASSWORD:-admin}` |
| RedisInsight | http://localhost:5540 | Redis inspect |

## Bước 5: Backfill embeddings (nếu đã có quiz public từ trước)

```bash
docker compose exec backend python -m scripts.backfill_embeddings
```

## Bước 6: Smoke test search

Mở http://localhost:8000/docs, lấy JWT token qua `/api/v1/auth/login`, rồi gọi:

```
GET /api/v1/search/quizzes?q=động+vật&top_k=5
Authorization: Bearer <token>
```

Lần đầu trả `[]` vì chưa có quiz public. Tạo 1 quiz public qua `POST /api/v1/quizzes/` rồi search lại — sẽ thấy quiz trong kết quả.

## Các lệnh thường dùng

```bash
# Stop toàn bộ
docker compose down

# Stop + xóa volumes (reset DB, Qdrant, Redis)
docker compose down -v

# Xem log 1 service
docker compose logs -f backend

# Vào shell trong container backend
docker compose exec backend bash

# Chạy script Python trong container backend
docker compose exec backend python -m scripts.backfill_embeddings

# Xem Qdrant collections
curl http://localhost:6333/collections

# Restart 1 service sau khi sửa code
docker compose restart backend
```

## Cấu trúc mạng Docker

```
host (browser)
   │
   ├── http://localhost:3000  →  frontend container
   │
   └── http://localhost:8000  →  backend container
                                    │
                                    ├── DATABASE_URL → db:5432 (postgres container)
                                    ├── REDIS_URL    → redis:6379 (redis container)
                                    └── QDRANT_URL   → qdrant:6333 (qdrant container)
                                                    │
                                                    └── outgoing HTTPS → api.shopaikey.com (Gemini proxy)
```

Tất cả service trong compose cùng default network, dùng **service name** làm hostname (không cần `localhost`).
