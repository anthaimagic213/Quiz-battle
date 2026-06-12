"""
SQL Tool - Build & execute safe SQL từ structured query.
Sử dụng SQLAlchemy core, không string concat -> chống injection.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, desc, asc, or_, not_, func, select, literal_column, text
from sqlalchemy.sql import operators
from sqlalchemy.sql.selectable import Select

from app.db.session import engine
from app.schemas.ai import SqlBlock, FilterBlock, OrderByBlock
from app.services.schema_catalog import get_schema_catalog, is_table_allowed
from app.services.sql_validator import validate_query, CatalogValidationError


# Map table name -> SQLAlchemy table object
# Lazy import để tránh circular
def _get_table_obj(table_name: str):
    from app.db.base_class import Base
    # Reflect table từ metadata
    table = Base.metadata.tables.get(f"public.{table_name}") or Base.metadata.tables.get(table_name)
    if table is None:
        raise CatalogValidationError(f"Table '{table_name}' not found in SQLAlchemy metadata")
    return table


def _resolve_placeholder(value: Any, current_user_id: UUID | None) -> Any:
    """Replace placeholder strings với giá trị thật."""
    if not isinstance(value, str):
        return value

    if value == "<current_user_id>":
        if current_user_id is None:
            raise ValueError("current_user_id required for this query")
        return str(current_user_id)

    if value == "<current_time>":
        return datetime.now(timezone.utc)

    if value == "<last_24_hours>":
        return datetime.now(timezone.utc) - timedelta(hours=24)

    if value == "<last_7_days>":
        return datetime.now(timezone.utc) - timedelta(days=7)

    if value == "<last_30_days>":
        return datetime.now(timezone.utc) - timedelta(days=30)

    return value


def _build_filter_clause(
    flt: FilterBlock,
    table_map: dict[str, Any],
    current_user_id: UUID | None,
):
    """Build một WHERE clause từ FilterBlock."""
    col_ref = flt.column
    if "." in col_ref:
        table_alias, col_name = col_ref.split(".", 1)
        table_obj = table_map[table_alias]
        col = table_obj.c[col_name]
    else:
        # Unqualified -> tìm table đầu tiên
        table_obj = table_map[list(table_map.keys())[0]]
        col = table_obj.c[col_ref]

    op = flt.op
    value = _resolve_placeholder(flt.value, current_user_id)

    if op == "=":
        return col == value
    elif op == "!=":
        return col != value
    elif op == ">":
        return col > value
    elif op == ">=":
        return col >= value
    elif op == "<":
        return col < value
    elif op == "<=":
        return col <= value
    elif op == "IN":
        return col.in_([_resolve_placeholder(v, current_user_id) for v in value])
    elif op == "NOT IN":
        return ~col.in_([_resolve_placeholder(v, current_user_id) for v in value])
    elif op == "LIKE":
        return col.like(value)
    elif op == "ILIKE":
        return col.ilike(value)
    elif op == "IS NULL":
        return col.is_(None)
    elif op == "IS NOT NULL":
        return col.isnot(None)
    else:
        raise ValueError(f"Unsupported operator: {op}")


def _build_order_by_clause(ob: OrderByBlock, table_map: dict[str, Any]):
    """Build ORDER BY clause."""
    col_ref = ob.column
    if "." in col_ref:
        table_alias, col_name = col_ref.split(".", 1)
        table_obj = table_map[table_alias]
        col = table_obj.c[col_name]
    else:
        table_obj = table_map[list(table_map.keys())[0]]
        col = table_obj.c[col_ref]

    return desc(col) if ob.direction == "DESC" else asc(col)


def _build_select_statement(
    query: SqlBlock,
    current_user_id: UUID | None,
) -> Select:
    """Build SQLAlchemy Select statement từ SqlBlock."""
    catalog = get_schema_catalog()
    table_map = {}

    for t in query.tables:
        if not is_table_allowed(t):
            raise CatalogValidationError(f"Table '{t}' not allowed")
        table_map[t] = _get_table_obj(t)

    # Base table
    base_table = table_map[query.tables[0]]
    stmt = select()

    # SELECT columns
    select_cols = []
    for col_ref in query.select:
        if col_ref.upper().startswith("COUNT(*)"):
            select_cols.append(func.count().label("count"))
            continue
        # Parse aggregate: COUNT(table.col)
        import re
        agg_match = re.match(r"(COUNT|SUM|AVG|MIN|MAX)\((\w+)\.(\w+)\)", col_ref, re.I)
        if agg_match:
            agg_func_name, table_alias, col_name = agg_match.groups()
            table_obj = table_map[table_alias]
            col = table_obj.c[col_name]
            if agg_func_name.upper() == "COUNT":
                select_cols.append(func.count(col).label(col_ref))
            elif agg_func_name.upper() == "SUM":
                select_cols.append(func.sum(col).label(col_ref))
            elif agg_func_name.upper() == "AVG":
                select_cols.append(func.avg(col).label(col_ref))
            elif agg_func_name.upper() == "MIN":
                select_cols.append(func.min(col).label(col_ref))
            elif agg_func_name.upper() == "MAX":
                select_cols.append(func.max(col).label(col_ref))
            continue

        # Regular column
        if "." in col_ref:
            table_alias, col_name = col_ref.split(".", 1)
            table_obj = table_map[table_alias]
        else:
            # Tìm table chứa column
            for t_obj in table_map.values():
                if col_ref in t_obj.c:
                    table_obj = t_obj
                    col_name = col_ref
                    break
            else:
                raise CatalogValidationError(f"Column '{col_ref}' not found")
        select_cols.append(table_obj.c[col_name].label(col_ref))

    stmt = stmt.add_columns(*select_cols)

    # FROM
    stmt = stmt.select_from(base_table)

    # JOINs
    joins_catalog = catalog.get("joins", {})
    for join_name in query.joins:
        join_def = joins_catalog[join_name]
        from_t = table_map[join_def["from_table"]]
        to_t = table_map[join_def["to_table"]]
        # Parse ON condition
        # VD: "quizzes.id = questions.quiz_id"
        on_parts = join_def["on"].split("=")
        left_ref = on_parts[0].strip()
        right_ref = on_parts[1].strip()

        left_t, left_c = left_ref.split(".")
        right_t, right_c = right_ref.split(".")

        if left_t == join_def["from_table"]:
            stmt = stmt.join(to_t, from_t.c[left_c] == to_t.c[right_c])
        else:
            stmt = stmt.join(to_t, from_t.c[right_c] == to_t.c[left_c])

    # WHERE
    if query.filters:
        where_clauses = [
            _build_filter_clause(f, table_map, current_user_id) for f in query.filters
        ]
        stmt = stmt.where(and_(*where_clauses))

    # GROUP BY
    if query.group_by:
        group_cols = []
        for col_ref in query.group_by:
            if "." in col_ref:
                t_alias, c_name = col_ref.split(".", 1)
                group_cols.append(table_map[t_alias].c[c_name])
            else:
                # Pick first table
                first_t = list(table_map.values())[0]
                group_cols.append(first_t.c[col_ref])
        stmt = stmt.group_by(*group_cols)

    # HAVING
    if query.having:
        having_clauses = []
        for flt in query.having:
            import re
            m = re.match(r"(COUNT|SUM|AVG|MIN|MAX)\((\w+)\)", flt.column, re.I)
            if m:
                agg_name, t_alias = m.groups()
                t_obj = table_map[t_alias]
                col = t_obj.c[list(t_obj.c.keys())[0]]  # placeholder
                agg_col = func.count() if agg_name.upper() == "COUNT" else func.sum(col)
                value = _resolve_placeholder(flt.value, current_user_id)
                op = flt.op
                if op == ">":
                    having_clauses.append(agg_col > value)
                elif op == ">=":
                    having_clauses.append(agg_col >= value)
                elif op == "<":
                    having_clauses.append(agg_col < value)
                elif op == "<=":
                    having_clauses.append(agg_col <= value)
                elif op == "=":
                    having_clauses.append(agg_col == value)
        if having_clauses:
            stmt = stmt.having(and_(*having_clauses))

    # ORDER BY
    if query.order_by:
        order_clauses = [_build_order_by_clause(ob, table_map) for ob in query.order_by]
        stmt = stmt.order_by(*order_clauses)

    # LIMIT
    stmt = stmt.limit(query.limit)

    return stmt


def execute_sql_query(
    query: SqlBlock,
    current_user_id: UUID | None = None,
    timeout_ms: int = 5000,
) -> dict:
    """
    Validate + execute SQL query an toàn.
    
    Returns:
        {
            "columns": [...],
            "rows": [...],
            "count": int,
            "elapsed_ms": int
        }
    
    Raises:
        CatalogValidationError: query không hợp lệ
        SQLAlchemyError: DB error
        TimeoutError: query quá chậm
    """
    start = time.time()

    # 1. Validate với schema catalog
    validate_query(query)

    # 2. Build SQLAlchemy statement
    stmt = _build_select_statement(query, current_user_id)

    # 3. Execute với timeout
    try:
        with engine.connect() as conn:
            # Set statement timeout (PostgreSQL)
            conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            result = conn.execute(stmt)
            rows = [dict(r._mapping) for r in result]
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        error_type = type(e).__name__
        raise SQLExecutionError(
            f"SQL execution failed: {error_type}: {str(e)[:200]} "
            f"(elapsed: {elapsed}ms)"
        ) from e

    elapsed = int((time.time() - start) * 1000)

    return {
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "count": len(rows),
        "elapsed_ms": elapsed,
    }


class SQLExecutionError(Exception):
    """Raised khi SQL execution fail."""
    pass
