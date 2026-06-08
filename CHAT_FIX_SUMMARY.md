# Tóm Tắt Sửa Lỗi Chat 2 Người

## Vấn Đề
Không gửi được tin nhắn trong phần chat 2 người khi chạy project trên Docker.

## 5 Bug Đã Sửa

### 🔴 Bug 1: Silent Drop trong `chatSocket.ts` (CRITICAL)
**Vấn đề:** Hàm `send()` chỉ gửi message khi `WebSocket.OPEN`. Nếu socket đang reconnect hoặc đóng, message bị mất mà không báo lỗi gì.

**Đã sửa:**
- Thêm message queue (tối đa 50 messages)
- Messages được queue khi socket không OPEN
- Khi socket kết nối lại, tự động flush queue
- Thêm method `isConnected()` để check trạng thái

**File:** `frontend/services/chatSocket.ts`

---

### 🔴 Bug 2: Hardcode WS URL (CRITICAL) 
**Vấn đề:** `chatSocket.ts` hardcode `ws://localhost:8000` thay vì dùng `NEXT_PUBLIC_WS_URL` env var.

**Đã sửa:**
```typescript
this.baseUrl = opts.baseUrl || process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
```

**File:** `frontend/services/chatSocket.ts`

---

### 🟡 Bug 3: Race Condition trong `ChatWindow.tsx`
**Vấn đề:** Component dùng `isSocketReady` flag nhưng chỉ set `true` khi nhận `CONVERSATION_JOINED`. Nếu user gửi message trước event này, message rơi vào nhánh WS nhưng socket chưa sẵn sàng.

**Đã sửa:** 
- Dùng `socketRef.current?.isConnected()` thay vì `isSocketReady`
- Check trực tiếp `WebSocket.OPEN` state
- Fallback về REST API nếu socket không connected

**File:** `frontend/components/social/ChatWindow.tsx`

---

### 🟡 Bug 4: Mark-Read API URL Mismatch
**Vấn đề:**
- Frontend gọi: `POST /conversations/{id}/messages/mark-read`
- Backend yêu cầu: `POST /conversations/{id}/messages/{message_id}/mark-read`

**Đã sửa:** Thêm endpoint mới không cần `message_id`:
```python
@router.post("/mark-read", response_model=dict)
async def mark_conversation_as_read(...)
```

**File:** `backend/app/api/v1/endpoints/messages.py`

---

### 🟡 Bug 5: Hai ConnectionManager Instances Riêng Biệt
**Vấn đề:** 
- `game_socket.py` có `manager = ConnectionManager()`
- `chat_socket.py` có `manager = ConnectionManager()` riêng
- Redis Pub/Sub listener chỉ wire với game_socket's manager
- → Messages từ chat_socket không đồng bộ qua Redis

**Đã sửa:**
- Tạo shared singleton `manager` trong `connection_manager.py`
- Cả `game_socket.py` và `chat_socket.py` đều import shared manager
- `main.py` import từ `connection_manager` thay vì `game_socket`

**Files:**
- `backend/app/websockets/connection_manager.py`
- `backend/app/websockets/game_socket.py`
- `backend/app/websockets/chat_socket.py`
- `backend/app/main.py`

---

## Cách Test

### 1. Rebuild Docker images
```bash
docker-compose down
docker-compose build
docker-compose up -d
```

### 2. Test chat 2 người
1. Đăng nhập 2 tài khoản khác nhau (2 browser hoặc incognito)
2. Kết bạn với nhau
3. Mở chat từ Friends Panel
4. Gửi tin nhắn từ user A → user B phải nhận được realtime
5. Gửi ngược lại từ user B → user A phải nhận được
6. Test trong các trường hợp:
   - Gửi ngay khi mở chat (WS chưa kết nối → fallback REST)
   - Gửi sau khi WS đã connected (realtime)
   - Tắt/bật network để test reconnect + queue

### 3. Check logs
```bash
# Backend logs
docker-compose logs -f backend

# Frontend logs  
docker-compose logs -f frontend
```

Tìm các log:
- `✅ Redis Pub/Sub listener started!` - Redis Pub/Sub OK
- `WebSocket connected` - WS connection thành công
- `WS recv: CHAT_MESSAGE` - Nhận được message qua WS

---

## Lưu Ý Khi Deploy Production

### 1. Set đúng NEXT_PUBLIC_WS_URL
Trong `.env` hoặc `docker-compose.yml`:
```yaml
NEXT_PUBLIC_WS_URL: wss://yourdomain.com
```

**Quan trọng:** Nếu deploy lên server, phải dùng domain thật chứ không phải `localhost`.

### 2. WebSocket qua NGINX/Reverse Proxy
Nếu dùng NGINX, cần config WebSocket upgrade:
```nginx
location /ws/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;
}
```

### 3. HTTPS/WSS
- Nếu frontend dùng HTTPS, WS phải dùng WSS (WebSocket Secure)
- Browser block mixed content (HTTPS → WS)

---

## Các Files Đã Thay Đổi

### Backend
1. `backend/app/websockets/connection_manager.py` - Shared singleton manager
2. `backend/app/websockets/game_socket.py` - Import shared manager
3. `backend/app/websockets/chat_socket.py` - Import shared manager
4. `backend/app/main.py` - Import manager từ connection_manager
5. `backend/app/api/v1/endpoints/messages.py` - Thêm `/mark-read` endpoint

### Frontend
1. `frontend/services/chatSocket.ts` - Queue, isConnected(), NEXT_PUBLIC_WS_URL
2. `frontend/components/social/ChatWindow.tsx` - Dùng isConnected() + REST fallback

---

## Troubleshooting

### Tin nhắn vẫn không gửi được?

**Check 1: WebSocket có kết nối không?**
- Mở DevTools → Network → WS tab
- Tìm connection tới `ws://localhost:8000/ws/chat/...`
- Status phải là `101 Switching Protocols`

**Check 2: Backend logs có lỗi không?**
```bash
docker-compose logs backend | grep -i error
```

**Check 3: Token có hợp lệ không?**
- Mở DevTools → Application → Local Storage
- Check `access_token` có tồn tại không
- Copy token, decode tại jwt.io để xem expiry

**Check 4: Database có conversation không?**
```bash
docker-compose exec db psql -U postgres -d quiz_battle -c "SELECT * FROM conversations;"
```

### Message gửi nhưng người kia không nhận được?

**Kiểm tra Redis Pub/Sub:**
```bash
docker-compose exec redis redis-cli
> SUBSCRIBE quizbattle:ws:broadcast
```
Gửi message từ chat, xem có event publish không.

**Kiểm tra cả 2 users đều kết nối WS:**
- Mở chat ở cả 2 browser
- Check Network → WS tab ở cả 2
- Phải thấy `CONVERSATION_JOINED` event

---

## Kết Luận

Tất cả các bug đã được sửa. Project giờ có thể:
✅ Gửi message qua WebSocket realtime
✅ Auto fallback về REST nếu WS không connected
✅ Queue messages khi WS đang reconnect
✅ Đồng bộ messages qua Redis Pub/Sub (multi-instance)
✅ Dùng env var cho WS URL (flexible deployment)

Rebuild Docker và test lại nhé!
