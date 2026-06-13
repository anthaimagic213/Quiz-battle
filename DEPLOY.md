# Hướng dẫn Deploy lên Server Thuê (VPS)

Tài liệu này dành cho việc deploy Quiz Battle lên 1 VPS / cloud server (DigitalOcean, Vultr, AWS Lightsail, VPS Việt Nam...).

> ⚠️ **ĐỌC TRƯỚC KHI LÀM:** Repo này từng chứa secret trong lịch sử git (đã xảy ra với `backend/.env` trong commit cũ). Vì GitHub là **public repo**, mọi secret từng xuất hiện trong history đều **phải coi là đã lộ** và cần rotate. Xem mục 0 dưới đây.

---

## 0. Trước khi deploy — ROTATE TOÀN BỘ SECRET CŨ

Vì repo public + đã từng commit `.env` chứa secret thật, bạn **bắt buộc** làm các bước sau trước khi đưa code lên server mới:

| Secret | Hành động rotate |
|---|---|
| `SECRET_KEY` | Generate key mới bằng `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `GEMINI_PROXY_API_KEY` | Vào https://api.shopaikey.com/ → Revoke key cũ, tạo key mới |
| `POSTGRES_PASSWORD` | Đổi thành password mạnh (24+ ký tự random) — KHÔNG dùng `7906` |
| Google OAuth client | Nếu đã từng public → tạo lại trong Google Cloud Console |
| SMTP password | Nếu dùng Gmail App Password → tạo lại |

**KHÔNG dùng lại** bất kỳ giá trị nào từ file `.env` cũ trong git history.

---

## 1. Chuẩn bị server

Yêu cầu tối thiểu:

- **OS:** Ubuntu 22.04 LTS (khuyến nghị) hoặc Debian 12
- **RAM:** ≥ 4GB (cho Postgres + Redis + Qdrant + Backend + Frontend)
- **CPU:** ≥ 2 vCPU
- **Disk:** ≥ 40GB SSD
- **Quyền:** `root` hoặc user có `sudo`
- **Domain:** trỏ về IP server (A record) — cần cho HTTPS

Cài Docker:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

---

## 2. Tạo file `.env` trên server

Trên server, **KHÔNG copy `.env` cũ**. Tạo mới từ template:

```bash
cd /opt/quiz-battle
cp .env.example.production .env
nano .env   # hoặc vim
```

Trong file `.env`, điền các giá trị THẬT (đã rotate ở bước 0):

```bash
# Mẫu — bạn phải thay giá trị thật của bạn
SECRET_KEY=<output của python -c "import secrets; print(secrets.token_urlsafe(64))">
POSTGRES_USER=quiz_app
POSTGRES_PASSWORD=<password mạnh 24+ ký tự>
POSTGRES_DB=quiz
GEMINI_PROXY_API_KEY=<key mới từ shopaikey>
ALLOWED_ORIGINS=["https://yourdomain.com","https://www.yourdomain.com"]
NEXT_PUBLIC_API_URL=https://yourdomain.com/api/v1
NEXT_PUBLIC_WS_URL=wss://yourdomain.com
# ... các biến optional khác (SMTP, Google OAuth) nếu dùng
```

**Kiểm tra quyền file** (không cho user khác đọc):

```bash
chmod 600 .env
ls -la .env   # phải hiện -rw------- owner owner
```

---

## 3. Chạy stack

```bash
# Pull & build lần đầu
docker compose up -d --build

# Xem log
docker compose logs -f backend

# Kiểm tra sức khỏe
docker compose ps
```

Nếu container nào thoát ngay (Exit 1), nghĩa là **thiếu biến môi trường bắt buộc** trong `.env` — `docker-compose.yml` được cấu hình fail-fast với syntax `${VAR:?message}`. Đọc log:

```bash
docker compose logs backend
```

---

## 4. Bắt buộc: Reverse Proxy + HTTPS

`docker-compose.yml` chỉ publish port `3000` (frontend) và `8000` (backend) ra host. **Production phải đặt Nginx + Let's Encrypt phía trước:**

### 4.1. Cài Nginx + Certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

### 4.2. File cấu hình Nginx `/etc/nginx/sites-available/quiz-battle`

```nginx
# Redirect to HTTPS
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Frontend Next.js
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket (cho real-time game)
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Chặn truy cập trực tiếp các service nội bộ nếu lộ port
    location /qdrant/ { return 404; }
    location /pgadmin/ { return 404; }
    location /redis/ { return 404; }
}
```

### 4.3. Enable + lấy chứng chỉ

```bash
sudo ln -s /etc/nginx/sites-available/quiz-battle /etc/nginx/sites-enabled/
sudo nginx -t
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
sudo systemctl reload nginx
```

Certbot tự động gia hạn — check với `sudo certbot renew --dry-run`.

---

## 5. Firewall (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# KHÔNG mở 5432, 6379, 6333, 8000 ra ngoài
sudo ufw enable
sudo ufw status
```

Đã có Nginx phía trước, user chỉ truy cập 80/443. Port backend (8000) chỉ Nginx mới gọi tới (`127.0.0.1`).

---

## 6. Auto-restart khi reboot

Docker đã có `restart: unless-stopped`. Kiểm tra Docker service:

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

Sau khi reboot, Docker tự khởi động + compose tự restart container.

---

## 7. Backup

### 7.1. Backup database (chạy cron hàng ngày)

```bash
# Tạo script
sudo nano /opt/quiz-battle/scripts/backup-db.sh
```

Nội dung:

```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR=/opt/backups/quiz-battle
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

docker exec quiz_battle_db pg_dump \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --no-owner --clean --if-exists \
    | gzip > "$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"

# Giữ 14 bản gần nhất
ls -1t "$BACKUP_DIR"/db_*.sql.gz | tail -n +15 | xargs -r rm --
echo "[$(date)] Backup done: db_${TIMESTAMP}.sql.gz"
```

```bash
chmod +x /opt/quiz-battle/scripts/backup-db.sh

# Cron chạy lúc 3h sáng hàng ngày
sudo crontab -e
# Thêm dòng:
0 3 * * * /opt/quiz-battle/scripts/backup-db.sh >> /var/log/quiz-battle-backup.log 2>&1
```

### 7.2. Backup volume Qdrant

```bash
# Stop qdrant trước khi backup
docker compose stop qdrant
sudo tar czf /opt/backups/qdrant_$(date +%Y%m%d).tar.gz /var/lib/docker/volumes/quiz-battle_qdrant_data
docker compose start qdrant
```

---

## 8. Cập nhật code (deploy phiên bản mới)

```bash
cd /opt/quiz-battle
git pull origin main
docker compose build --pull          # pull base image mới
docker compose up -d                 # restart với image mới
docker compose logs -f backend       # kiểm tra log
```

Database migration (nếu có Alembic):

```bash
docker compose exec backend alembic upgrade head
```

---

## 9. Checklist bảo mật trước khi go-live

- [ ] Tất cả secret trong `.env` đã được rotate (không dùng lại từ git history)
- [ ] `chmod 600 .env` — chỉ owner đọc được
- [ ] UFW bật, chỉ mở 22, 80, 443
- [ ] Nginx đặt phía trước, không lộ port 8000/3000 trực tiếp ra internet
- [ ] HTTPS hoạt động (certbot), HTTP tự redirect về HTTPS
- [ ] `BACKEND_DEBUG=false` trong `.env`
- [ ] `POSTGRES_PASSWORD` là password mạnh (24+ ký tự random)
- [ ] Backup DB chạy tự động + test restore 1 lần
- [ ] Server có fail2ban (chống SSH brute force): `sudo apt install -y fail2ban`
- [ ] Auto update OS: `sudo apt install -y unattended-upgrades`
- [ ] `.git` không bị mount vào container production (đã OK trong config hiện tại)

---

## 10. Lệnh hữu ích

```bash
# Xem log real-time
docker compose logs -f

# Restart 1 service
docker compose restart backend

# Vào Postgres
docker exec -it quiz_battle_db psql -U quiz_app -d quiz

# Xem resource usage
docker stats

# Disk usage của volumes
docker system df -v

# Dọn rác (volume cũ, image không dùng)
docker system prune -a --volumes    # CẨN THẬN: xóa cả volume!
```
