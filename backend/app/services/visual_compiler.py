"""
Visual Studio Query Compiler.

Compiles a validated visual specification into ONE read-only, safe DuckDB SELECT.
All column identifiers are quoted via qid() and filter values safely escaped/parameterized.
Never string-concatenates untrusted user text into SQL keywords.
"""
from __future__ import annotations

import re
from typing import Any
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from .util import qid
from .visual_registry import APPLICABLE_OPTIONS_MATRIX, DROPDOWN_OPTIONS, VISUAL_TYPES


class VisualFilter(BaseModel):
    field: str
    operator: str
    value: Any = None
    value_to: Any = None  # for 'between'


class VisualSpec(BaseModel):
    id: str | None = None
    type: str
    title: str = "Visual"
    dataset_id: str
    version: int | None = None
    sheet: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    filters: list[VisualFilter] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VISUAL_TYPES:
            raise ValueError(f"Unknown visual type '{v}'. Must be one of {list(VISUAL_TYPES.keys())}")
        return v


class VisualCompileError(ValueError):
    pass


def _safe_escape_literal(val: Any) -> str:
    """Safely escape values for SQL literals."""
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    # String escaping: replace ' with '' and quote
    s = str(val).replace("'", "''")
    return f"'{s}'"


def _clean_ident(col: str) -> str:
    """Ensure identifier does not contain illegal characters or SQL injection attempts."""
    col = str(col).strip()
    if not col:
        raise VisualCompileError("Empty column name")
    # Disallow semicolons, comments, or quotes inside unquoted identifier
    if any(c in col for c in [";", "--", "/*", "*/"]):
        raise VisualCompileError(f"Invalid characters in field name: {col}")
    return qid(col)


def _agg_expr(agg: str, col_expr: str, order_expr: str | None = None) -> str:
    """Compile aggregation function to DuckDB SQL expression."""
    agg = (agg or "sum").lower()
    if agg == "sum":
        return f"SUM({col_expr})"
    elif agg in ("average", "avg"):
        return f"AVG({col_expr})"
    elif agg == "count":
        return f"COUNT({col_expr})"
    elif agg in ("distinct_count", "count_distinct"):
        return f"COUNT(DISTINCT {col_expr})"
    elif agg == "median":
        return f"MEDIAN({col_expr})"
    elif agg == "min":
        return f"MIN({col_expr})"
    elif agg == "max":
        return f"MAX({col_expr})"
    elif agg == "pct_of_total":
        return f"100.0 * SUM({col_expr}) / NULLIF(SUM(SUM({col_expr})) OVER (), 0)"
    elif agg == "running_total":
        ord_clause = f"ORDER BY {order_expr} ASC" if order_expr else "ORDER BY 1"
        return f"SUM(SUM({col_expr})) OVER ({ord_clause} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"
    else:
        return f"SUM({col_expr})"


def _date_grain_expr(grain: str, col_expr: str) -> str:
    """Compile date grain to DuckDB date_trunc / strftime expression."""
    grain = (grain or "month").lower()
    if grain == "day":
        return f"CAST(date_trunc('day', CAST({col_expr} AS TIMESTAMP)) AS DATE)"
    elif grain == "week":
        return f"CAST(date_trunc('week', CAST({col_expr} AS TIMESTAMP)) AS DATE)"
    elif grain == "month":
        return f"CAST(date_trunc('month', CAST({col_expr} AS TIMESTAMP)) AS DATE)"
    elif grain == "quarter":
        return f"CAST(date_trunc('quarter', CAST({col_expr} AS TIMESTAMP)) AS DATE)"
    elif grain == "year":
        return f"CAST(date_trunc('year', CAST({col_expr} AS TIMESTAMP)) AS DATE)"
    elif grain == "weekday":
        return f"strftime(CAST({col_expr} AS TIMESTAMP), '%A')"
    elif grain == "hour":
        return f"strftime(CAST({col_expr} AS TIMESTAMP), '%Y-%m-%d %H:00')"
    else:
        return f"CAST(date_trunc('month', CAST({col_expr} AS TIMESTAMP)) AS DATE)"


def _compile_filter(f: VisualFilter) -> str:
    """Compile a single VisualFilter into SQL predicate."""
    col = _clean_ident(f.field)
    op = (f.operator or "is").lower()
    v = f.value

    if op in ("is", "equals", "="):
        return f"{col} = {_safe_escape_literal(v)}"
    elif op in ("is_not", "!="):
        return f"({col} != {_safe_escape_literal(v)} OR {col} IS NULL)"
    elif op == "contains":
        esc = str(v or "").replace("'", "''").replace("%", "\\%")
        return f"CAST({col} AS VARCHAR) ILIKE '%{esc}%'"
    elif op in ("gt", ">"):
        return f"{col} > {_safe_escape_literal(v)}"
    elif op in ("lt", "<"):
        return f"{col} < {_safe_escape_literal(v)}"
    elif op == "between":
        v1 = _safe_escape_literal(v)
        v2 = _safe_escape_literal(f.value_to if f.value_to is not None else v)
        return f"{col} BETWEEN {v1} AND {v2}"
    elif op in ("is_empty", "null"):
        return f"({col} IS NULL OR CAST({col} AS VARCHAR) = '')"
    elif op in ("is_not_empty", "not_null"):
        return f"({col} IS NOT NULL AND CAST({col} AS VARCHAR) != '')"
    else:
        return f"{col} = {_safe_escape_literal(v)}"


def compile_visual_to_sql(
    table_name: str,
    spec: VisualSpec,
    page_filters: list[VisualFilter] | None = None,
    available_columns: list[str] | None = None,
) -> str:
    """
    Compile a validated VisualSpec + page filters into a single read-only DuckDB query.
    Returns SQL query string.
    """
    vtype = spec.type
    matrix = APPLICABLE_OPTIONS_MATRIX.get(vtype)
    if not matrix:
        raise VisualCompileError(f"Unsupported visual type: {vtype}")

    opts = spec.options or {}
    fields = spec.fields or {}

    # Validate required fields
    for rf in matrix.get("required_fields", []):
        if rf not in fields or not fields[rf]:
            # Fallback if fields is incomplete, use sensible default or raise
            raise VisualCompileError(f"Field '{rf}' is required for visual type '{vtype}'")

    # Combine filters
    all_filters = (spec.filters or []) + (page_filters or [])
    where_clauses = []
    for f in all_filters:
        if f.field:
            where_clauses.append(_compile_filter(f))

    # Handle missing values option
    missing_mode = opts.get("missing_values", "ignore")

    tbl = qid(table_name)
    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Sort & Limit helpers
    sort_mode = opts.get("sort", "value_desc")
    show_mode = opts.get("show", "all")
    limit_clause = ""
    if show_mode == "top_5":
        limit_clause = " LIMIT 5"
    elif show_mode == "top_10":
        limit_clause = " LIMIT 10"
    elif show_mode == "top_20":
        limit_clause = " LIMIT 20"
    elif show_mode == "bottom_5":
        limit_clause = " LIMIT 5"
    elif show_mode == "bottom_10":
        limit_clause = " LIMIT 10"

    agg = opts.get("aggregation", "sum")

    # ─────────────────────────────────────────────────────────────────────────
    # 1. KPI CARD / GAUGE / BULLET
    # ─────────────────────────────────────────────────────────────────────────
    if vtype in ("kpi_card", "gauge", "bullet"):
        val_col = _clean_ident(fields["value"])
        agg_sql = _agg_expr(agg, val_col)
        sql = f"SELECT {agg_sql} AS \"value\" FROM {tbl}{where_sql}"
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 2. SPARKLINE KPI
    # ─────────────────────────────────────────────────────────────────────────
    if vtype == "sparkline_kpi":
        val_col = _clean_ident(fields["value"])
        cat_col = _clean_ident(fields["category"])
        grain = opts.get("date_grain", "month")
        grain_expr = _date_grain_expr(grain, cat_col)
        agg_sql = _agg_expr(agg, val_col)

        sql = (
            f"SELECT {grain_expr} AS \"period\", {agg_sql} AS \"value\" "
            f"FROM {tbl}{where_sql} "
            f"GROUP BY 1 ORDER BY 1 ASC LIMIT 24"
        )
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 3. HISTOGRAM
    # ─────────────────────────────────────────────────────────────────────────
    if vtype == "histogram":
        val_col = _clean_ident(fields["value"])
        sql = f"SELECT {val_col} AS \"value\" FROM {tbl}{where_sql} WHERE {val_col} IS NOT NULL LIMIT 5000"
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 4. SCATTER & BUBBLE
    # ─────────────────────────────────────────────────────────────────────────
    if vtype in ("scatter", "bubble"):
        x_col = _clean_ident(fields["x"])
        y_col = _clean_ident(fields["y"])
        select_cols = [f"{x_col} AS \"x\"", f"{y_col} AS \"y\""]
        if vtype == "bubble" and "size" in fields and fields["size"]:
            select_cols.append(f"{_clean_ident(fields['size'])} AS \"size\"")
        if "colour_by" in fields and fields["colour_by"]:
            select_cols.append(f"{_clean_ident(fields['colour_by'])} AS \"color\"")

        sql = f"SELECT {', '.join(select_cols)} FROM {tbl}{where_sql} WHERE {x_col} IS NOT NULL AND {y_col} IS NOT NULL LIMIT 2000"
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 5. BOX PLOT
    # ─────────────────────────────────────────────────────────────────────────
    if vtype == "box":
        val_col = _clean_ident(fields["value"])
        cat_col = _clean_ident(fields.get("category", fields["value"]))
        select_cols = [f"{val_col} AS \"value\""]
        if "category" in fields and fields["category"]:
            select_cols.append(f"{cat_col} AS \"category\"")
        sql = f"SELECT {', '.join(select_cols)} FROM {tbl}{where_sql} WHERE {val_col} IS NOT NULL LIMIT 5000"
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 6. TABLE (multi-column)
    # ─────────────────────────────────────────────────────────────────────────
    if vtype == "table":
        cols = fields.get("columns", [])
        if isinstance(cols, str):
            cols = [cols]
        if not cols:
            cols = ["*"]
            select_sql = "*"
        else:
            select_sql = ", ".join([_clean_ident(c) for c in cols])

        order_sql = ""
        if sort_mode == "value_desc":
            order_sql = " ORDER BY 1 DESC"
        elif sort_mode == "value_asc":
            order_sql = " ORDER BY 1 ASC"

        sql = f"SELECT {select_sql} FROM {tbl}{where_sql}{order_sql}{limit_clause or ' LIMIT 100'}"
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 7. HEATMAP & PIVOT
    # ─────────────────────────────────────────────────────────────────────────
    if vtype in ("heatmap", "pivot"):
        rows_col = _clean_ident(fields["rows"])
        cols_col = _clean_ident(fields["columns"])
        val_col = _clean_ident(fields["value"])
        agg_sql = _agg_expr(agg, val_col)

        sql = (
            f"SELECT {rows_col} AS \"row\", {cols_col} AS \"col\", {agg_sql} AS \"value\" "
            f"FROM {tbl}{where_sql} "
            f"GROUP BY 1, 2 ORDER BY 1, 2 LIMIT 500"
        )
        return sql

    # ─────────────────────────────────────────────────────────────────────────
    # 8. STANDARD CATEGORY + VALUE (COLUMN, BAR, STACKED, LINE, AREA, PIE, DONUT, TREEMAP, FUNNEL)
    # ─────────────────────────────────────────────────────────────────────────
    cat_field = fields.get("category")
    if not cat_field:
        raise VisualCompileError(f"Category field is required for {vtype}")
    cat_col = _clean_ident(cat_field)

    val_field = fields.get("value")
    if not val_field:
        raise VisualCompileError(f"Value field is required for {vtype}")
    val_col = _clean_ident(val_field)

    # Date grain application if category is a date
    if vtype in ("line", "area") and opts.get("date_grain"):
        cat_expr = _date_grain_expr(opts.get("date_grain"), cat_col)
    else:
        cat_expr = cat_col

    agg_sql = _agg_expr(agg, val_col, order_expr=cat_expr)

    colour_by = fields.get("colour_by")
    if colour_by and vtype in ("stacked_column", "stacked_bar", "column", "bar", "line", "area", "combo", "likert_stack"):
        col_by = _clean_ident(colour_by)
        group_sql = f"{cat_expr}, {col_by}"
        select_sql = f"{cat_expr} AS \"category\", {col_by} AS \"series\", {agg_sql} AS \"value\""
    else:
        group_sql = f"{cat_expr}"
        select_sql = f"{cat_expr} AS \"category\", {agg_sql} AS \"value\""

    # Sorting
    if agg == "running_total":
        order_sql = " ORDER BY \"category\" ASC"
    elif sort_mode == "value_desc":
        order_sql = " ORDER BY \"value\" DESC"
    elif sort_mode == "value_asc":
        order_sql = " ORDER BY \"value\" ASC"
    elif sort_mode == "label_asc":
        order_sql = " ORDER BY \"category\" ASC"
    elif sort_mode == "label_desc":
        order_sql = " ORDER BY \"category\" DESC"
    elif sort_mode == "date":
        order_sql = " ORDER BY \"category\" ASC"
    else:
        order_sql = " ORDER BY \"value\" DESC"

    # If show is bottom N, invert sort direction for inner query then re-sort
    if show_mode in ("bottom_5", "bottom_10"):
        order_sql = " ORDER BY \"value\" ASC"

    sql = f"SELECT {select_sql} FROM {tbl}{where_sql} GROUP BY {group_sql}{order_sql}{limit_clause}"
    return sql
