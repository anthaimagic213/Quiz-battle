"""
Test script - kiểm tra Schema Catalog + SQL Validator.
Chạy: python -m pytest backend/tests/test_phase3_catalog.py -v
"""

import pytest
from app.services.schema_catalog import (
    get_schema_catalog,
    is_table_allowed,
    is_column_selectable,
    is_column_filterable,
    is_forbidden_column,
)
from app.services.sql_validator import (
    validate_query,
    CatalogValidationError,
)
from app.schemas.ai import SqlBlock, FilterBlock, OrderByBlock


def test_schema_catalog_structure():
    """Test catalog có đủ tables và joins."""
    catalog = get_schema_catalog()
    
    assert "tables" in catalog
    assert "joins" in catalog
    assert "examples" in catalog
    
    # Check một số bảng quan trọng
    assert "users" in catalog["tables"]
    assert "quizzes" in catalog["tables"]
    assert "questions" in catalog["tables"]
    assert "user_stats" in catalog["tables"]
    
    # Check joins
    assert "quizzes__questions" in catalog["joins"]
    assert "users__user_stats" in catalog["joins"]


def test_table_allowed():
    """Test is_table_allowed."""
    assert is_table_allowed("users") is True
    assert is_table_allowed("quizzes") is True
    assert is_table_allowed("nonexistent_table") is False
    assert is_table_allowed("password_resets") is False  # không trong catalog


def test_column_selectable():
    """Test is_column_selectable."""
    # users.username selectable
    assert is_column_selectable("users", "username") is True
    # users.email KHÔNG selectable (forbidden)
    assert is_column_selectable("users", "email") is False
    # quizzes.title selectable
    assert is_column_selectable("quizzes", "title") is True


def test_forbidden_columns():
    """Test forbidden columns không bao giờ được select."""
    assert is_forbidden_column("users", "email") is True
    assert is_forbidden_column("users", "password_hash") is True
    assert is_forbidden_column("users", "username") is False


def test_column_filterable():
    """Test is_column_filterable."""
    # users.username filterable
    assert is_column_filterable("users", "username") is True
    # users.email KHÔNG filterable
    assert is_column_filterable("users", "email") is False
    # quizzes.is_public filterable
    assert is_column_filterable("quizzes", "is_public") is True


def test_validate_simple_query():
    """Test validate query đơn giản."""
    query = SqlBlock(
        tables=["users"],
        joins=[],
        select=["username", "full_name", "created_at"],
        filters=[],
        order_by=[OrderByBlock(column="created_at", direction="DESC")],
        limit=10,
    )
    
    # Không raise = pass
    validate_query(query)


def test_validate_query_with_join():
    """Test validate query có join."""
    query = SqlBlock(
        tables=["users", "user_stats"],
        joins=["users__user_stats"],
        select=["users.username", "user_stats.wins"],
        filters=[],
        order_by=[OrderByBlock(column="user_stats.wins", direction="DESC")],
        limit=5,
    )
    
    validate_query(query)


def test_validate_query_with_filters():
    """Test validate query có filters."""
    query = SqlBlock(
        tables=["quizzes"],
        joins=[],
        select=["id", "title", "created_at"],
        filters=[
            FilterBlock(column="is_public", op="=", value=True),
            FilterBlock(column="is_deleted", op="=", value=False),
            FilterBlock(column="created_at", op=">=", value="<last_7_days>"),
        ],
        order_by=[OrderByBlock(column="created_at", direction="DESC")],
        limit=20,
    )
    
    validate_query(query)


def test_validate_query_forbidden_table():
    """Test query bảng không có trong catalog."""
    query = SqlBlock(
        tables=["password_resets"],
        joins=[],
        select=["id"],
        filters=[],
        limit=10,
    )
    
    with pytest.raises(CatalogValidationError, match="not in catalog"):
        validate_query(query)


def test_validate_query_forbidden_column():
    """Test select cột forbidden (email, password_hash)."""
    query = SqlBlock(
        tables=["users"],
        joins=[],
        select=["username", "email"],  # email forbidden
        filters=[],
        limit=10,
    )
    
    with pytest.raises(CatalogValidationError, match="forbidden"):
        validate_query(query)


def test_validate_query_non_selectable_column():
    """Test select cột không selectable."""
    query = SqlBlock(
        tables=["users"],
        joins=[],
        select=["username", "avatar_url"],  # avatar_url không trong catalog
        filters=[],
        limit=10,
    )
    
    with pytest.raises(CatalogValidationError):
        validate_query(query)


def test_validate_query_invalid_join():
    """Test join không có trong catalog."""
    query = SqlBlock(
        tables=["users", "quizzes"],
        joins=["users__quizzes"],  # join này không tồn tại
        select=["users.username"],
        filters=[],
        limit=10,
    )
    
    with pytest.raises(CatalogValidationError, match="not in catalog"):
        validate_query(query)


def test_validate_query_missing_join_table():
    """Test join yêu cầu bảng không có trong tables."""
    query = SqlBlock(
        tables=["users"],  # thiếu user_stats
        joins=["users__user_stats"],
        select=["users.username"],
        filters=[],
        limit=10,
    )
    
    with pytest.raises(CatalogValidationError, match="requires table"):
        validate_query(query)


if __name__ == "__main__":
    print("=== Test Schema Catalog ===")
    test_schema_catalog_structure()
    print("[OK] Catalog structure")
    
    test_table_allowed()
    print("[OK] Table allowed")
    
    test_column_selectable()
    print("[OK] Column selectable")
    
    test_forbidden_columns()
    print("[OK] Forbidden columns")
    
    test_column_filterable()
    print("[OK] Column filterable")
    
    print("\n=== Test SQL Validator ===")
    test_validate_simple_query()
    print("[OK] Simple query")
    
    test_validate_query_with_join()
    print("[OK] Query with join")
    
    test_validate_query_with_filters()
    print("[OK] Query with filters")
    
    print("\n=== Test Validation Errors ===")
    test_validate_query_forbidden_table()
    print("[OK] Forbidden table caught")
    
    test_validate_query_forbidden_column()
    print("[OK] Forbidden column caught")
    
    test_validate_query_invalid_join()
    print("[OK] Invalid join caught")
    
    test_validate_query_missing_join_table()
    print("[OK] Missing join table caught")
    
    print("\n=== All tests passed ===")
