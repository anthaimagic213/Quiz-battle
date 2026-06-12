"""
Backward-compat shim: app.core.database -> app.db.session
File này tồn tại để các module cũ (sql_tool.py, v.v.) vẫn import được.
Ưu tiên dùng: from app.db.session import engine
"""
from app.db.session import engine, SessionLocal, get_db  # noqa: F401

__all__ = ["engine", "SessionLocal", "get_db"]
