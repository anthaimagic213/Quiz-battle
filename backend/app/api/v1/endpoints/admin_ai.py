"""
Admin endpoints để monitor và quản lý AI services.

- GET /api/admin/ai/status - xem trạng thái circuit breakers
- POST /api/admin/ai/circuit-breakers/reset - reset tất cả circuit breakers
- GET /api/admin/ai/catalog - xem schema catalog
"""

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user
from app.schemas.user import User

router = APIRouter()


@router.get("/status")
def get_ai_status(current_user: User = Depends(get_current_user)):
    """
    Get AI service status (circuit breakers, LLM config).
    Admin only.
    """
    # TODO: check if user is admin
    # if not current_user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin only")
    
    from app.services.llm_service import get_llm_status
    
    return get_llm_status()


@router.post("/circuit-breakers/reset")
def reset_circuit_breakers(current_user: User = Depends(get_current_user)):
    """
    Reset all circuit breakers (admin use).
    Admin only.
    """
    # TODO: check if user is admin
    # if not current_user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin only")
    
    from app.services.llm_service import reset_llm_circuit_breakers
    
    reset_llm_circuit_breakers()
    
    return {"message": "All circuit breakers reset successfully"}


@router.get("/catalog")
def get_schema_catalog_endpoint(current_user: User = Depends(get_current_user)):
    """
    Get SQL schema catalog (whitelist).
    Admin only.
    """
    # TODO: check if user is admin
    # if not current_user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin only")
    
    from app.services.schema_catalog import (
        get_schema_catalog,
        MAX_JOINS,
        MAX_LIMIT,
        REQUIRE_LIMIT,
        ALLOWED_AGGREGATES,
        ALLOWED_DATE_FUNCTIONS,
    )
    
    catalog = get_schema_catalog()
    
    return {
        "catalog": catalog,
        "config": {
            "max_joins": MAX_JOINS,
            "max_limit": MAX_LIMIT,
            "require_limit": REQUIRE_LIMIT,
            "allowed_aggregates": ALLOWED_AGGREGATES,
            "allowed_date_functions": ALLOWED_DATE_FUNCTIONS,
        },
    }


@router.get("/function-schemas")
def get_function_schemas(current_user: User = Depends(get_current_user)):
    """
    Get function calling schemas.
    Admin only.
    """
    # TODO: check if user is admin
    
    from app.services.function_schemas import (
        get_router_function_schema,
        get_sql_query_function_schema,
    )
    
    return {
        "router": get_router_function_schema(),
        "sql_query": get_sql_query_function_schema(),
    }
