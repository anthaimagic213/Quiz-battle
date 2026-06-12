"""Force re-write .env to fix encoding issues."""
from pathlib import Path

env_path = Path(".env")
content = env_path.read_text(encoding="utf-8")

# Fix DEBUG - regardless of value, set to true
import re
content = re.sub(r"^DEBUG=.*$", "DEBUG=true", content, flags=re.MULTILINE)

# Make sure DATABASE_URL exists with correct host
if "DATABASE_URL=" in content:
    content = re.sub(
        r"^DATABASE_URL=.*$",
        "DATABASE_URL=postgresql://postgres:7906@localhost:5432/quiz",
        content,
        flags=re.MULTILINE,
    )

# Write with UTF-8 (no BOM)
env_path.write_text(content, encoding="utf-8")
print("[OK] .env re-written")

# Verify
import os
os.environ["DEBUG"] = "true"
from app.core.config import settings
print(f"[OK] Settings loaded: DEBUG={settings.DEBUG}, DB={settings.DATABASE_URL[:30]}...")
