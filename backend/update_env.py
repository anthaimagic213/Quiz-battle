"""
Helper script - cập nhật .env cho local development.
Chạy: cd backend && python update_env.py
"""

import re
from pathlib import Path

env_path = Path(__file__).parent / ".env"
content = env_path.read_text(encoding="utf-8")

# 1. Đổi POSTGRES_HOST=db thành localhost (cho local dev)
content = re.sub(
    r"POSTGRES_HOST=db",
    "POSTGRES_HOST=localhost",
    content,
)

# 2. Thêm DATABASE_URL nếu chưa có
if "DATABASE_URL=" not in content:
    content = re.sub(
        r"(POSTGRES_PORT=5432)",
        r"\1\nDATABASE_URL=postgresql://postgres:7906@localhost:5432/quiz",
        content,
    )

# 3. Đổi QDRANT_URL cho local (không phải docker)
content = re.sub(
    r"QDRANT_URL=http://qdrant:6333",
    "QDRANT_URL=http://localhost:6333",
    content,
)

# 4. REDIS_URL cho local
content = re.sub(
    r"REDIS_URL=redis://redis:6379/0",
    "REDIS_URL=redis://localhost:6379/0",
    content,
)

env_path.write_text(content, encoding="utf-8")
print("[OK] .env updated for local development")
print()
print("Updated values:")
for line in content.splitlines():
    if any(k in line for k in ["POSTGRES_HOST", "DATABASE_URL", "QDRANT_URL", "REDIS_URL", "GEMINI_PROXY_API_KEY"]):
        if "=" not in line:
            continue
        # Ẩn key
        if "API_KEY" in line:
            parts = line.split("=", 1)
            key = parts[1] if len(parts) > 1 else ""
            masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
            print(f"  {parts[0]}={masked}")
        else:
            print(f"  {line}")
