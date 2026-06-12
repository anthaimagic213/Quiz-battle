"""
Debug endpoint để test SQL query trực tiếp.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_db, get_current_user_obj
from app.models.user_auth.users import User
from app.services.sql_tool import execute_sql_query
from app.services.ai_orchestrator import _build_get_my_stats_sql
from app.schemas.ai import SqlBlock

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/my-stats")
def debug_my_stats(
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint: test SQL query cho user_stats.
    """
    try:
        # Build SQL
        sql_block = _build_get_my_stats_sql(current_user.id)
        
        # Execute
        result = execute_sql_query(
            query=sql_block,
            current_user_id=current_user.id,
            timeout_ms=5000,
        )
        
        return {
            "user_id": str(current_user.id),
            "sql_block": sql_block.model_dump(),
            "result": result,
        }
    
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "user_id": str(current_user.id),
        }


@router.post("/test-sql")
def debug_test_sql(
    sql_block: SqlBlock,
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint: test arbitrary SQL query.
    """
    try:
        result = execute_sql_query(
            query=sql_block,
            current_user_id=current_user.id,
            timeout_ms=5000,
        )
        
        return {
            "user_id": str(current_user.id),
            "result": result,
        }
    
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@router.get("/check-user-stats-table")
def debug_check_table(
    current_user: User = Depends(get_current_user_obj),
    db: Session = Depends(get_db),
):
    """
    Check nếu user có record trong user_stats.
    """
    from sqlalchemy import text
    
    result = db.execute(
        text("SELECT * FROM user_stats WHERE user_id = :user_id"),
        {"user_id": str(current_user.id)}
    ).fetchone()
    
    if result:
        return {
            "exists": True,
            "data": dict(result._mapping),
        }
    else:
        return {
            "exists": False,
            "message": "User chưa có record trong user_stats. Cần chơi ít nhất 1 game.",
            "user_id": str(current_user.id),
        }
