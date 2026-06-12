"""
Validator cho SQL query dựa trên Schema Catalog.
Đảm bảo LLM không bypass được whitelist.
"""

from app.services.schema_catalog import (
    get_schema_catalog,
    get_enum_values,
    is_table_allowed,
    is_column_selectable,
    is_column_filterable,
    is_forbidden_column,
    ALLOWED_AGGREGATES,
    ALLOWED_DATE_FUNCTIONS,
    MAX_JOINS,
    MAX_LIMIT,
    REQUIRE_LIMIT,
)
from app.schemas.ai import SqlBlock, FilterBlock
import re

# Placeholder patterns
PLACEHOLDER_PATTERN = re.compile(r"^<[a-z_0-9]+>$")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Aggregate pattern: COUNT(*) | COUNT(table.col) | SUM(col)
AGGREGATE_PATTERN = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\((?:(\*)|(?:(\w+)\.)?(\w+))\)(?:\s+AS\s+(\w+))?$",
    re.I,
)

# Date function pattern: DATE_TRUNC('day', col) | EXTRACT(YEAR FROM col)
DATE_FUNC_PATTERN = re.compile(
    r"^(DATE_TRUNC|EXTRACT|NOW|CURRENT_DATE|CURRENT_TIMESTAMP)",
    re.I,
)


class CatalogValidationError(Exception):
    """Raised khi query không pass schema catalog validation."""
    pass


def _parse_column_ref(col: str) -> tuple[str, str]:
    """
    Parse column reference thành (table_alias, column_name).
    VD: "quizzes.title" -> ("quizzes", "title")
        "title" -> ("", "title")  # unqualified
    """
    if "." in col:
        parts = col.split(".", 1)
        return parts[0], parts[1]
    return "", col


def _validate_value(value: object, col_def: dict) -> None:
    """Validate value phù hợp với column type."""
    col_type = col_def.get("type", "string")

    if value is None:
        return  # IS NULL case handled by op

    if isinstance(value, str) and PLACEHOLDER_PATTERN.match(value):
        # Placeholder: <current_user_id>, <last_7_days>, <last_30_days>, etc.
        return

    if col_type == "uuid":
        if isinstance(value, str) and UUID_PATTERN.match(value):
            return
        raise CatalogValidationError(f"Invalid UUID value: {value}")

    if col_type == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return
        raise CatalogValidationError(f"Invalid int value: {value}")

    if col_type == "float":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return
        raise CatalogValidationError(f"Invalid float value: {value}")

    if col_type == "bool":
        if isinstance(value, bool):
            return
        raise CatalogValidationError(f"Invalid bool value: {value}")

    if col_type == "datetime":
        if isinstance(value, str):
            # Accept ISO format or placeholder
            try:
                from dateutil import parser
                parser.isoparse(value)
                return
            except (ValueError, ImportError):
                pass
        raise CatalogValidationError(f"Invalid datetime value: {value}")

    if col_type.startswith("enum:"):
        enum_name = col_type.split(":", 1)[1]
        allowed = get_enum_values(enum_name)
        if allowed and value in allowed:
            return
        raise CatalogValidationError(f"Invalid enum value '{value}', expected one of {allowed}")

    if col_type == "string":
        if isinstance(value, str):
            return
        raise CatalogValidationError(f"Invalid string value: {value}")


def _is_aggregate_expr(col_ref: str) -> bool:
    """Check xem col_ref có phải aggregate expression không."""
    return bool(AGGREGATE_PATTERN.match(col_ref))


def _is_date_function_expr(col_ref: str) -> bool:
    """Check xem col_ref có phải date function không."""
    return bool(DATE_FUNC_PATTERN.match(col_ref))


def _validate_aggregate(col_ref: str, table_aliases: dict[str, str]) -> None:
    """Validate aggregate expression."""
    match = AGGREGATE_PATTERN.match(col_ref)
    if not match:
        raise CatalogValidationError(f"Invalid aggregate syntax: {col_ref}")
    
    agg_func = match.group(1).upper()
    is_star = match.group(2) == "*"
    table_alias = match.group(3)
    col_name = match.group(4)
    
    # Check function trong whitelist
    if agg_func not in ALLOWED_AGGREGATES and f"{agg_func}(*)" not in ALLOWED_AGGREGATES:
        raise CatalogValidationError(
            f"Aggregate function '{agg_func}' not allowed. "
            f"Allowed: {', '.join(ALLOWED_AGGREGATES)}"
        )
    
    # COUNT(*) không cần check table
    if is_star:
        return
    
    # Check table alias tồn tại
    if table_alias and table_alias not in table_aliases:
        raise CatalogValidationError(f"Unknown table alias in aggregate: {table_alias}")


def _validate_date_function(col_ref: str, table_aliases: dict[str, str]) -> None:
    """Validate date function expression."""
    # Extract function name
    match = DATE_FUNC_PATTERN.match(col_ref)
    if not match:
        raise CatalogValidationError(f"Invalid date function syntax: {col_ref}")
    
    func_name = match.group(1).upper()
    
    if func_name not in ALLOWED_DATE_FUNCTIONS:
        raise CatalogValidationError(
            f"Date function '{func_name}' not allowed. "
            f"Allowed: {', '.join(ALLOWED_DATE_FUNCTIONS)}"
        )
    
    # Basic syntax check
    if func_name == "DATE_TRUNC":
        # DATE_TRUNC('day', column)
        if not re.match(r"DATE_TRUNC\('[^']+',\s*[\w.]+\)", col_ref, re.I):
            raise CatalogValidationError(
                f"Invalid DATE_TRUNC syntax: {col_ref}. "
                f"Expected: DATE_TRUNC('unit', column)"
            )
    elif func_name == "EXTRACT":
        # EXTRACT(YEAR FROM column)
        if not re.match(r"EXTRACT\(\w+\s+FROM\s+[\w.]+\)", col_ref, re.I):
            raise CatalogValidationError(
                f"Invalid EXTRACT syntax: {col_ref}. "
                f"Expected: EXTRACT(unit FROM column)"
            )


def _validate_filter(
    flt: FilterBlock,
    table_aliases: dict[str, str],
    catalog: dict,
) -> None:
    """Validate một filter block."""
    table_alias, col_name = _parse_column_ref(flt.column)

    # Resolve table name từ alias nếu có
    if table_alias:
        if table_alias not in table_aliases:
            raise CatalogValidationError(f"Unknown table alias: {table_alias}")
        table_name = table_aliases[table_alias]
    else:
        # Unqualified column -> phải thuộc một trong các tables
        # Tìm table đầu tiên có column này trong allowed_filters
        for t in table_aliases.values():
            tbl = catalog["tables"].get(t)
            if tbl and col_name in tbl["allowed_filters"]:
                table_name = t
                break
        else:
            raise CatalogValidationError(
                f"Column '{col_name}' not in allowed_filters of any table"
            )

    # Check column có trong allowed_filters không
    if not is_column_filterable(table_name, col_name):
        raise CatalogValidationError(
            f"Column '{col_name}' not filterable in table '{table_name}'"
        )

    # Check forbidden
    if is_forbidden_column(table_name, col_name):
        raise CatalogValidationError(
            f"Column '{col_name}' is forbidden in table '{table_name}'"
        )

    # Get column def for value validation
    table_def = catalog["tables"][table_name]
    col_def = table_def["columns"].get(col_name)
    if not col_def:
        raise CatalogValidationError(f"Column '{col_name}' not defined in '{table_name}'")

    # Validate value theo type
    if flt.op in ("IN", "NOT IN"):
        if not isinstance(flt.value, list):
            raise CatalogValidationError(f"'{flt.op}' requires list value")
        for v in flt.value:
            _validate_value(v, col_def)
    elif flt.op in ("IS NULL", "IS NOT NULL"):
        if flt.value is not None:
            raise CatalogValidationError(f"'{flt.op}' should have null value")
    else:
        _validate_value(flt.value, col_def)


def validate_query(query: SqlBlock) -> None:
    """
    Validate SqlBlock khớp với Schema Catalog.
    Raise CatalogValidationError nếu invalid.
    
    New validations:
    - MAX_JOINS: tối đa 3 JOIN
    - REQUIRE_LIMIT: LIMIT bắt buộc
    - Aggregate functions whitelist
    - Date functions whitelist
    - Subquery support (limited)
    """
    catalog = get_schema_catalog()
    tables = catalog["tables"]
    joins = catalog.get("joins", {})

    # 1. Validate tables
    if not query.tables:
        raise CatalogValidationError("At least one table required")

    for t in query.tables:
        if not is_table_allowed(t):
            raise CatalogValidationError(f"Table '{t}' not in catalog")

    # Build table_aliases mapping (alias = table name khi không có AS)
    table_aliases = {t: t for t in query.tables}

    # 2. Validate joins - CHECK MAX_JOINS
    if len(query.joins) > MAX_JOINS:
        raise CatalogValidationError(
            f"Too many joins: {len(query.joins)} (max {MAX_JOINS})"
        )
    
    for join_name in query.joins:
        if join_name not in joins:
            raise CatalogValidationError(f"Join '{join_name}' not in catalog")
        join_def = joins[join_name]
        # Cả 2 bảng phải có trong query.tables
        if join_def["from_table"] not in query.tables:
            raise CatalogValidationError(
                f"Join '{join_name}' requires table '{join_def['from_table']}'"
            )
        if join_def["to_table"] not in query.tables:
            raise CatalogValidationError(
                f"Join '{join_name}' requires table '{join_def['to_table']}'"
            )

    # 3. Validate select columns
    if not query.select:
        raise CatalogValidationError("At least one select column required")

    for col_ref in query.select:
        # Validate aggregate functions
        if _is_aggregate_expr(col_ref):
            _validate_aggregate(col_ref, table_aliases)
            continue
        
        # Validate date functions
        if _is_date_function_expr(col_ref):
            _validate_date_function(col_ref, table_aliases)
            continue

        table_alias, col_name = _parse_column_ref(col_ref)

        if table_alias:
            if table_alias not in table_aliases:
                raise CatalogValidationError(f"Unknown table alias in select: {table_alias}")
            table_name = table_aliases[table_alias]
        else:
            # Tìm table chứa column này
            found = False
            for t in query.tables:
                tbl = tables[t]
                if col_name in tbl["columns"]:
                    table_name = t
                    found = True
                    break
            if not found:
                raise CatalogValidationError(f"Column '{col_name}' not in any table")
            table_alias = table_name

        # Check forbidden TRƯỚC khi check selectable
        if is_forbidden_column(table_name, col_name):
            raise CatalogValidationError(
                f"Column '{col_name}' is forbidden in '{table_name}'"
            )

        if not is_column_selectable(table_name, col_name):
            raise CatalogValidationError(
                f"Column '{col_name}' not selectable in '{table_name}'"
            )

    # 4. Validate filters
    for flt in query.filters:
        _validate_filter(flt, table_aliases, catalog)

    # 5. Validate group_by
    for col_ref in query.group_by:
        table_alias, col_name = _parse_column_ref(col_ref)
        if table_alias and table_alias not in table_aliases:
            raise CatalogValidationError(f"Unknown table alias in group_by: {table_alias}")
        if not is_column_selectable(table_alias or query.tables[0], col_name):
            raise CatalogValidationError(f"Column '{col_name}' not in group_by")

    # 6. Validate having
    for flt in query.having:
        # Having chỉ check syntax, không check filterable (vì có thể là aggregate)
        match = re.match(r"(COUNT|SUM|AVG|MIN|MAX)\((\w+)\)", flt.column, re.I)
        if not match:
            raise CatalogValidationError(
                f"Having must be aggregate function: {flt.column}"
            )
        table_alias = match.group(2)
        if table_alias not in table_aliases and table_alias != "*":
            raise CatalogValidationError(f"Unknown table in having: {table_alias}")

    # 7. Validate order_by
    for ob in query.order_by:
        table_alias, col_name = _parse_column_ref(ob.column)
        if table_alias and table_alias not in table_aliases:
            raise CatalogValidationError(f"Unknown table alias in order_by: {table_alias}")
        if not is_column_selectable(table_alias or query.tables[0], col_name):
            raise CatalogValidationError(f"Column '{col_name}' not orderable")

    # 8. Validate limit - REQUIRE_LIMIT
    if REQUIRE_LIMIT and (not query.limit or query.limit <= 0):
        raise CatalogValidationError("LIMIT is required and must be > 0")
    
    if query.limit and query.limit > MAX_LIMIT:
        raise CatalogValidationError(
            f"LIMIT too high: {query.limit} (max {MAX_LIMIT})"
        )
