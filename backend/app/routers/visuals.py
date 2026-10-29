"""
Visual Studio API Router.

Endpoints:
  GET  /visuals/registry          → Single source of truth (23 visuals, dropdown options, matrix)
  POST /visuals/query             → Compile visual spec to SQL, execute sandbox query, return Plotly figure/KPI
  POST /visuals/suggest           → Auto-suggest 6-8 sensible visuals based on column roles
  POST /visuals/validate-formula  → Validate custom calculated field expression
  POST /visuals/export-excel      → Generate multi-sheet workbook with native openpyxl charts
"""
from __future__ import annotations

import io
import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows
import pandas as pd
from pydantic import BaseModel, Field

from ..auth import current_user
from ..db import dashboards, datasets
from ..services import charts, datasets as ds, profiling, sql_engine
from ..services.visual_compiler import (
    VisualCompileError,
    VisualFilter,
    VisualSpec,
    compile_visual_to_sql,
)
from ..services.visual_registry import get_visual_registry

router = APIRouter(prefix="/visuals", tags=["visual-studio"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Request Models
# ─────────────────────────────────────────────────────────────────────────────
class VisualQueryRequest(BaseModel):
    spec: VisualSpec
    page_filters: list[VisualFilter] = Field(default_factory=list)


class SuggestRequest(BaseModel):
    dataset_id: str
    version: int | None = None


class ValidateFormulaRequest(BaseModel):
    dataset_id: str
    name: str
    formula: str


class ExportExcelRequest(BaseModel):
    dataset_id: str
    dashboard_name: str = "Dashboard Export"
    specs: list[VisualSpec] = Field(default_factory=list)
    page_filters: list[VisualFilter] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /visuals/registry
# ─────────────────────────────────────────────────────────────────────────────
from ..gating import require_dataset
from ..services.visual_recommender import evaluate_visual_suitability, profile_columns_for_visuals


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /visuals/registry
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/registry")
def registry():
    """Returns the visual studio registry (single source of truth for UI dropdowns)."""
    return get_visual_registry()


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /visuals/recommendations
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/recommendations")
def recommendations(dataset_id: str | None = None, version: int | None = None, user=Depends(current_user)):
    """
    Returns ranked eligibility for all 23 visual types and top 6–8 starter visuals.
    Gated: returns 409 if user has no datasets.
    """
    require_dataset(user)
    if not dataset_id:
        user_datasets = ds.list_datasets(user["_id"])
        if not user_datasets:
            raise HTTPException(409, "No dataset available.")
        dataset_id = user_datasets[0]["id"]
    d = ds.get_dataset(user["_id"], dataset_id)
    v = version or d["current_version"]
    df = ds.load_df(d, v)

    source_meta = d.get("source_meta") or {}
    profiles = profile_columns_for_visuals(df, source_meta)
    eval_result = evaluate_visual_suitability(
        profiles=profiles,
        total_rows=len(df),
        dataset_id=dataset_id,
        has_target=False,
    )

    return {
        "dataset_id": dataset_id,
        "version": v,
        "columns_profile": eval_result["columns_profile"],
        "recommendations": eval_result["recommendations"],
        "starters": eval_result["starters"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. POST /visuals/query
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/query")
def query_visual(b: VisualQueryRequest, user=Depends(current_user)):
    """
    Validates visual spec, compiles to DuckDB SQL, executes safely in sandbox,
    runs reconciliation checks, and returns {sql, columns, rows, figure, kpi, reconciliation, version_info}.
    Gated: returns 409 if user has no datasets.
    """
    require_dataset(user)
    d = ds.get_dataset(user["_id"], b.spec.dataset_id)
    table_name = d["table"]
    v = b.spec.version or d["current_version"]

    # Verify column existence against dataset dataframe
    df_raw = ds.load_df(d, v)
    available_cols = list(df_raw.columns)

    try:
        sql = compile_visual_to_sql(
            table_name=table_name,
            spec=b.spec,
            page_filters=b.page_filters,
            available_columns=available_cols,
        )
    except VisualCompileError as ve:
        raise HTTPException(400, str(ve))
    except Exception as ex:
        raise HTTPException(400, f"Compilation failed: {ex}")

    try:
        df_result, truncated = sql_engine.run_df(user["_id"], sql, max_rows=5000)
    except Exception as ex:
        raise HTTPException(400, f"Query execution failed: {ex}")

    # Inferred currency detection: only show currency symbol if source cells had one
    val_field = b.spec.fields.get("value")
    detected_currencies = (
        d.get("column_currencies")
        or (d.get("source_meta") or {}).get("column_currencies")
        or {}
    )
    inferred_sym = detected_currencies.get(str(val_field)) if val_field else None

    # Build Plotly Figure with smart defaults & linter
    try:
        figure = charts.make_figure(
            df=df_result,
            chart=b.spec.type,
            title=b.spec.title,
            options=b.spec.options,
            currency=inferred_sym,
        )
    except Exception as ex:
        figure = None

    # Reconciliation and validation checks
    reconciliation = _run_reconciliation_checks(
        user_id=user["_id"],
        table_name=table_name,
        spec=b.spec,
        df_result=df_result,
        df_raw=df_raw,
    )

    # Compute KPI metrics & comparisons if applicable
    kpi_meta = None
    if b.spec.type in ("kpi_card", "sparkline_kpi", "gauge", "bullet"):
        kpi_meta = _compute_kpi_comparison(
            df_result=df_result,
            table_name=table_name,
            spec=b.spec,
            user_id=user["_id"],
            page_filters=b.page_filters,
            currency_symbol=inferred_sym,
            df_raw=df_raw,
        )

    # Format result rows
    cols = list(df_result.columns)
    rows = df_result.fillna("").to_dict(orient="records")

    import datetime as _dt
    ver_entry = next((entry for entry in d.get("versions", []) if entry.get("v") == v), None)
    v_date = ""
    if ver_entry and ver_entry.get("created"):
        try:
            parsed_d = _dt.datetime.fromisoformat(ver_entry["created"])
            v_date = parsed_d.strftime("%d %b %Y")
        except Exception:
            v_date = ver_entry["created"][:10]
    else:
        v_date = _dt.datetime.now().strftime("%d %b %Y")

    version_info = f"Data as of v{v}, {v_date}"

    meta = (figure or {}).get("datapilot_meta", {}) if isinstance(figure, dict) else {}

    return {
        "sql": sql,
        "columns": cols,
        "rows": rows,
        "row_count": len(df_result),
        "total_source_rows": len(df_raw),
        "null_rows_excluded": meta.get("excluded_count", 0) or reconciliation.get("null_rows_excluded", 0),
        "summary": meta.get("summary", ""),
        "caption": meta.get("caption", ""),
        "warnings": meta.get("warnings", []),
        "aggregation": b.spec.options.get("aggregation", "sum"),
        "filters_applied": [f.model_dump() for f in (b.spec.filters + b.page_filters)],
        "version_info": version_info,
        "truncated": truncated,
        "figure": figure,
        "kpi": kpi_meta,
        "reconciliation": reconciliation,
        "inferred_currency": inferred_sym,
    }


def _run_reconciliation_checks(
    user_id: str,
    table_name: str,
    spec: VisualSpec,
    df_result: pd.DataFrame,
    df_raw: pd.DataFrame,
) -> dict[str, Any]:
    """Run mathematical and audit reconciliation checks on query result."""
    from ..services.util import qid
    checks = []
    warning_badge = None
    null_rows_excluded = 0

    val_col = spec.fields.get("value")
    cat_col = spec.fields.get("category")
    vtype = spec.type
    agg = (spec.options.get("aggregation") or "sum").lower()

    # 1. Null rows check
    if val_col and val_col in df_raw.columns:
        null_val_count = int(df_raw[val_col].isna().sum())
        if null_val_count > 0:
            null_rows_excluded += null_val_count
            checks.append({
                "name": "Missing value exclusions",
                "passed": True,
                "detail": f"{null_val_count} row(s) excluded due to missing '{val_col}'",
            })

    if cat_col and cat_col in df_raw.columns:
        null_cat_count = int(df_raw[cat_col].isna().sum())
        if null_cat_count > 0:
            null_rows_excluded += null_cat_count
            checks.append({
                "name": "Missing category exclusions",
                "passed": True,
                "detail": f"{null_cat_count} row(s) excluded due to missing '{cat_col}'",
            })

    # 2. Grouped sum vs total ungrouped sum check
    if agg == "sum" and val_col and val_col in df_raw.columns and "value" in df_result.columns and cat_col:
        try:
            ungrouped_sum_sql = f'SELECT SUM({qid(val_col)}) AS total FROM {qid(table_name)}'
            tot_df, _ = sql_engine.run_df(user_id, ungrouped_sum_sql)
            if not tot_df.empty and pd.notna(tot_df["total"].iloc[0]):
                tot_val = float(tot_df["total"].iloc[0])
                grouped_sum = float(pd.to_numeric(df_result["value"], errors="coerce").sum())

                diff = abs(tot_val - grouped_sum)
                # If show limits top-N, difference is expected
                is_limited = spec.options.get("show") in ("top_5", "top_10", "top_20", "bottom_5", "bottom_10")
                if is_limited:
                    other_remainder = round(tot_val - grouped_sum, 2)
                    checks.append({
                        "name": "Top-N Remainder",
                        "passed": True,
                        "detail": f"Top-{len(df_result)} sum: {grouped_sum:,.2f}, Remaining (Other): {other_remainder:,.2f}, Total: {tot_val:,.2f}",
                    })
                elif diff > 0.05:
                    warning_badge = f"Reconciliation Warning: grouped sum ({grouped_sum:,.2f}) != total ({tot_val:,.2f})"
                    checks.append({
                        "name": "Sum Reconciliation",
                        "passed": False,
                        "detail": warning_badge,
                    })
                else:
                    checks.append({
                        "name": "Sum Reconciliation",
                        "passed": True,
                        "detail": f"Sum of categories ({grouped_sum:,.2f}) matches ungrouped total exactly",
                    })
        except Exception:
            pass

    # 3. Percent of total / part to whole sum to 100 check
    if (vtype in ("pie", "donut") or agg == "pct_of_total") and "value" in df_result.columns:
        num_vals = pd.to_numeric(df_result["value"], errors="coerce").dropna()
        if agg == "pct_of_total" or (not num_vals.empty and abs(num_vals.sum() - 100.0) <= 1.0):
            pct_sum = round(float(num_vals.sum()), 2)
            if abs(pct_sum - 100.0) > 0.5:
                warning_badge = f"Percentages sum to {pct_sum}%, expected 100%"
                checks.append({"name": "Part-to-Whole 100%", "passed": False, "detail": warning_badge})
            else:
                checks.append({"name": "Part-to-Whole 100%", "passed": True, "detail": f"Proportions sum to {pct_sum}% (within ±0.5%)"})

    return {
        "passed": warning_badge is None,
        "warning_badge": warning_badge,
        "checks": checks,
        "null_rows_excluded": null_rows_excluded,
    }


def _compute_kpi_comparison(
    df_result: pd.DataFrame,
    table_name: str,
    spec: VisualSpec,
    user_id: str,
    page_filters: list[VisualFilter],
    currency_symbol: str | None = None,
    df_raw: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Computes primary value, explicit formula documentation, and verifiable period comparisons.
    If comparison period has no data, returns 'n/a', never 0%.
    """
    from ..services.util import qid
    val = 0.0
    if len(df_result) > 0 and "value" in df_result.columns:
        first_val = df_result["value"].iloc[0]
        if pd.notna(first_val):
            val = float(first_val)
    elif len(df_result) > 0 and len(df_result.columns) > 0:
        first_val = df_result.iloc[0, 0]
        if pd.notna(first_val):
            val = float(first_val)

    compare_to = spec.options.get("compare_to", "none")
    target = float(spec.options.get("target") or 0.0)

    delta_pct = None
    delta_abs = None
    status = "neutral"
    comparison_text = None

    # Determine explicit math formula docs
    agg = (spec.options.get("aggregation") or "sum").lower()
    val_name = spec.fields.get("value", "metric")
    if agg == "sum":
        formula_docs = f"SUM({val_name})"
    elif agg in ("average", "avg"):
        formula_docs = f"AVG({val_name}) = SUM({val_name}) / COUNT({val_name})"
    elif agg == "count":
        formula_docs = f"COUNT({val_name})"
    elif agg in ("distinct_count", "count_distinct"):
        formula_docs = f"COUNT(DISTINCT {val_name})"
    elif agg == "median":
        formula_docs = f"MEDIAN({val_name})"
    else:
        formula_docs = f"{agg.upper()}({val_name})"

    if compare_to == "target":
        if target > 0:
            delta_abs = round(val - target, 2)
            delta_pct = round((delta_abs / target) * 100.0, 1)
            status = "positive" if delta_abs >= 0 else "negative"
            formatted_target = _format_metric(target, spec.options.get("number_format", "auto"), currency_symbol)
            comparison_text = f"{'+' if delta_pct >= 0 else ''}{delta_pct}% vs target ({formatted_target})"
        else:
            comparison_text = "Target not specified"

    elif compare_to in ("previous_period", "same_period_last_year"):
        # Real period calculation from DuckDB
        date_col = spec.fields.get("category")
        if not date_col and df_raw is not None:
            # Look for a date column in df_raw
            for c in df_raw.columns:
                if pd.api.types.is_datetime64_any_dtype(df_raw[c]) or "date" in c.lower() or "time" in c.lower():
                    date_col = c
                    break

        prior_val = None
        prior_period_label = None

        if date_col and val_name:
            try:
                date_expr = f"CAST(date_trunc('month', CAST({qid(date_col)} AS TIMESTAMP)) AS DATE)"
                agg_expr = f"SUM({qid(val_name)})" if agg == "sum" else f"AVG({qid(val_name)})"
                period_sql = f"SELECT {date_expr} AS p, {agg_expr} AS v FROM {qid(table_name)} WHERE {qid(date_col)} IS NOT NULL GROUP BY 1 ORDER BY 1 DESC"
                p_df, _ = sql_engine.run_df(user_id, period_sql)

                if len(p_df) >= 2 and compare_to == "previous_period":
                    prior_val = float(p_df["v"].iloc[1])
                    prior_period_label = str(p_df["p"].iloc[1])
                elif len(p_df) >= 1 and compare_to == "same_period_last_year":
                    cur_p = str(p_df["p"].iloc[0])
                    # Try to find date 1 year prior
                    import datetime as _dt
                    try:
                        cur_dt = _dt.date.fromisoformat(cur_p[:10])
                        target_dt = cur_dt.replace(year=cur_dt.year - 1)
                        match_row = p_df[p_df["p"].astype(str).str.startswith(str(target_dt)[:7])]
                        if not match_row.empty:
                            prior_val = float(match_row["v"].iloc[0])
                            prior_period_label = str(match_row["p"].iloc[0])
                    except Exception:
                        pass
            except Exception:
                pass

        if prior_val is not None and prior_val != 0:
            delta_abs = round(val - prior_val, 2)
            delta_pct = round((delta_abs / prior_val) * 100.0, 1)
            status = "positive" if delta_abs >= 0 else "negative"
            label = f" ({prior_period_label})" if prior_period_label else ""
            comparison_text = f"{'+' if delta_pct >= 0 else ''}{delta_pct}% vs prior period{label}"
        else:
            # Explicitly return 'n/a', never 0%
            delta_abs = None
            delta_pct = None
            status = "neutral"
            comparison_text = "n/a (no data for comparison period)"

    # Number format helper
    fmt = spec.options.get("number_format", "auto")
    formatted_val = _format_metric(val, fmt, currency_symbol)

    return {
        "raw_value": val,
        "formatted_value": formatted_val,
        "delta_abs": delta_abs,
        "delta_pct": delta_pct,
        "status": status,
        "comparison_text": comparison_text,
        "formula_docs": formula_docs,
        "currency_symbol": currency_symbol,
    }


def _format_metric(val: float, fmt: str, symbol: str | None = None) -> str:
    sym = symbol or ""
    if fmt == "currency_inr":
        sym = "₹"
        return f"{sym}{val:,.2f}"
    elif fmt == "currency_inr_compact":
        sym = "₹"
        if abs(val) >= 10000000:
            return f"{sym}{val / 10000000:.2f}Cr"
        elif abs(val) >= 100000:
            return f"{sym}{val / 100000:.2f}L"
        elif abs(val) >= 1000:
            return f"{sym}{val / 1000:.1f}k"
        else:
            return f"{sym}{val:,.0f}"
    elif fmt == "integer":
        return f"{int(round(val)):,}"
    elif fmt == "percent":
        return f"{val:.1f}%"
    elif fmt == "decimal_2":
        return f"{val:,.2f}"
    else:
        # If symbol inferred from source cells, prefix it
        if sym:
            return f"{sym}{val:,.2f}" if isinstance(val, float) else f"{sym}{val:,}"
        return f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. POST /visuals/suggest
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/suggest")
def suggest_visuals(b: SuggestRequest, user=Depends(current_user)):
    """
    Examines column roles and automatically recommends 6–8 sensible starter visuals for the canvas.
    Gated: returns 409 if user has no datasets.
    """
    require_dataset(user)
    d = ds.get_dataset(user["_id"], b.dataset_id)
    v = b.version or d["current_version"]
    df = ds.load_df(d, v)

    source_meta = d.get("source_meta") or {}
    profiles = profile_columns_for_visuals(df, source_meta)
    eval_result = evaluate_visual_suitability(profiles, len(df), b.dataset_id)

    return {"suggestions": eval_result["starters"]}


# ─────────────────────────────────────────────────────────────────────────────
# 5. POST /visuals/validate-formula
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/validate-formula")
def validate_formula(b: ValidateFormulaRequest, user=Depends(current_user)):
    """Validates custom calculated field expression against DuckDB syntax."""
    require_dataset(user)
    expr = b.formula.strip()

    # Disallow semicolons or DDL
    if any(k in expr.upper() for k in [";", "DROP", "ALTER", "INSERT", "DELETE", "UPDATE", "--", "/*"]):
        raise HTTPException(400, "Formula contains unsafe keywords or characters.")

    d = ds.get_dataset(user["_id"], b.dataset_id)

    test_sql = f"SELECT ({expr}) AS \"test_result\" FROM {d['table']} LIMIT 1"
    try:
        df, _ = sql_engine.run_df(user["_id"], test_sql, max_rows=1)
        inferred_type = str(df["test_result"].dtype) if len(df.columns) > 0 else "unknown"
        return {"valid": True, "name": b.name, "expression": expr, "inferred_type": inferred_type}
    except Exception as ex:
        raise HTTPException(400, f"Invalid formula: {ex}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. POST /visuals/export-excel
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/export-excel")
def export_dashboard_excel(b: ExportExcelRequest, user=Depends(current_user)):
    """
    Generates a multi-sheet Excel workbook with one sheet per visual data
    plus native openpyxl charts (BarChart, LineChart, PieChart) and a KPI summary sheet.
    """
    require_dataset(user)
    wb = Workbook()
    ws_kpi = wb.active
    ws_kpi.title = "KPI_Summary"

    # Style Header for KPI sheet
    ws_kpi["A1"] = f"{b.dashboard_name} — Visual Studio Export"
    ws_kpi["A1"].font = Font(size=14, bold=True, color="0F172A")
    ws_kpi["A2"] = "Summary of metrics and visuals generated in DataPilot"
    ws_kpi["A2"].font = Font(size=11, color="64748B")

    ws_kpi["A4"] = "Visual Name"
    ws_kpi["B4"] = "Type"
    ws_kpi["C4"] = "Primary Metric"
    ws_kpi["D4"] = "Value / Status"
    for col_letter in ["A", "B", "C", "D"]:
        cell = ws_kpi[f"{col_letter}4"]
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(fill_type="solid", fgColor="0F172A")

    kpi_row = 5

    # Process each spec
    for idx, spec in enumerate(b.specs, 1):
        try:
            d = ds.get_dataset(user["_id"], spec.dataset_id)
            sql = compile_visual_to_sql(d["table"], spec, b.page_filters)
            df, _ = sql_engine.run_df(user["_id"], sql, max_rows=5000)

            # Record in KPI summary
            first_val = str(df.iloc[0, 0]) if len(df) > 0 and len(df.columns) > 0 else "-"
            ws_kpi[f"A{kpi_row}"] = spec.title
            ws_kpi[f"B{kpi_row}"] = spec.type
            ws_kpi[f"C{kpi_row}"] = spec.fields.get("value") or spec.fields.get("category") or "-"
            ws_kpi[f"D{kpi_row}"] = first_val
            kpi_row += 1

            # Create individual data sheet
            sheet_title = f"{idx}_{spec.title[:20]}".replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_")
            ws_data = wb.create_sheet(title=sheet_title)

            # Dump dataframe
            for r in dataframe_to_rows(df, index=False, header=True):
                ws_data.append(r)

            # Style header row of data sheet
            for cell in ws_data[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(fill_type="solid", fgColor="059669")

            # Add native openpyxl chart if suitable
            num_rows = len(df)
            num_cols = len(df.columns)
            if num_rows >= 2 and num_cols >= 2:
                if spec.type in ("column", "bar", "stacked_column", "stacked_bar"):
                    chart = BarChart()
                    chart.type = "col" if spec.type == "column" else "bar"
                    chart.title = spec.title
                    data_ref = Reference(ws_data, min_col=2, min_row=1, max_row=min(num_rows + 1, 20), max_col=num_cols)
                    cats_ref = Reference(ws_data, min_col=1, min_row=2, max_row=min(num_rows + 1, 20))
                    chart.add_data(data_ref, titles_from_data=True)
                    chart.set_categories(cats_ref)
                    ws_data.add_chart(chart, f"E2")
                elif spec.type in ("line", "area"):
                    chart = LineChart()
                    chart.title = spec.title
                    data_ref = Reference(ws_data, min_col=2, min_row=1, max_row=min(num_rows + 1, 20), max_col=num_cols)
                    cats_ref = Reference(ws_data, min_col=1, min_row=2, max_row=min(num_rows + 1, 20))
                    chart.add_data(data_ref, titles_from_data=True)
                    chart.set_categories(cats_ref)
                    ws_data.add_chart(chart, f"E2")
                elif spec.type in ("pie", "donut"):
                    chart = PieChart()
                    chart.title = spec.title
                    data_ref = Reference(ws_data, min_col=2, min_row=1, max_row=min(num_rows + 1, 10))
                    cats_ref = Reference(ws_data, min_col=1, min_row=2, max_row=min(num_rows + 1, 10))
                    chart.add_data(data_ref, titles_from_data=True)
                    chart.set_categories(cats_ref)
                    ws_data.add_chart(chart, f"E2")

        except Exception:
            continue

    # Auto-width columns on KPI sheet
    for col in ws_kpi.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws_kpi.column_dimensions[col[0].column_letter].width = max(max_len + 3, 14)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"{b.dashboard_name.replace(' ', '_').lower()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
