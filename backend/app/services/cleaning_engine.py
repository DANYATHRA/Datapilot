"""Comprehensive, deterministic Data Cleaning Engine for Datapilot.

Provides configurable operations with transparent audit tracking:
- Missing values (detection, custom markers, imputation, dropping)
- Duplicates (exact, key-based, keep first/last/remove all, keep all flagged)
- Column names & text normalization (snake_case, trim, spacing, case, category merge)
- Data type conversion (numeric, date formats, boolean, string with leading zeros)
- Business validation rules (ranges, non-negative, date bounds, allowed categories, regex, email)
- Outlier handling (IQR, Z-score, flag-only default, capping/winsorizing, dropping)
- Structural checks (empty rows/cols, constant columns)
- PII masking and data sanitization
- Audit log & comprehensive cleaning report generation
- Cell-level and row-level before/after change tracking with stable row identifiers
"""
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import re
import time
import uuid
from typing import Any

import numpy as np
import pandas as pd

from ..config import settings
from .profiling import CURRENCY_CHARS, profile
from .util import text_cols

ENGINE_VERSION = "2.0.0"
ROW_ID_COL = "__dp_row_id__"


class CleaningEngineError(ValueError):
    pass


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _safe_val(v: Any, max_len: int = 70) -> Any:
    """Format a value safely for audit logs and report tables."""
    if v is None or pd.isna(v):
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return round(float(v), 4) if not np.isinf(v) else str(v)
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    s = str(v).strip()
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _are_different(a: Any, b: Any) -> bool:
    """Accurately test if two values are different, properly handling NaNs."""
    if pd.isna(a) and pd.isna(b):
        return False
    if pd.isna(a) != pd.isna(b):
        return True
    try:
        return bool(a != b)
    except Exception:
        return str(a) != str(b)


def snake_case_name(name: str) -> str:
    """Convert arbitrary column name to clean snake_case."""
    s = re.sub(r"[^\w\s-]", "", str(name).strip()).strip()
    s = re.sub(r"[-\s]+", "_", s)
    s = s.lower()
    return s or "column"


def deduplicate_column_names(cols: list[str]) -> list[str]:
    """Ensure column names are unique without silently overwriting columns."""
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        base = c
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n}")
    return out


# ── Operation Handlers ─────────────────────────────────────────────────────────

def op_missing_values(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Handle missing values according to user configuration with detailed cell/row tracking."""
    df = df.copy()
    action = params.get("action", "keep")
    all_valid_cols = [c for c in df.columns if c != ROW_ID_COL]
    target_cols = params.get("columns") or ([params["column"]] if params.get("column") else all_valid_cols)
    target_cols = [c for c in target_cols if c in df.columns and c != ROW_ID_COL]
    custom_markers = params.get("custom_null_markers") or []

    detailed_changes: list[dict[str, Any]] = []
    rows_before = len(df)
    cols_before = len([c for c in df.columns if c != ROW_ID_COL])
    cells_marked = 0

    # 1. Standardize custom null markers in text columns to NaN first
    if custom_markers:
        markers_set = {str(m).strip().lower() for m in custom_markers if str(m).strip()}
        for c in target_cols:
            if c in df.columns:
                is_text = df[c].dtype == object or str(df[c].dtype).startswith("string")
                if is_text or df[c].isna().any():
                    str_s = df[c].astype(str).str.strip().str.lower()
                    mask_marker = str_s.isin(markers_set) & df[c].notna()
                    count = int(mask_marker.sum())
                    if count > 0:
                        cells_marked += count
                        for idx in df[mask_marker].index:
                            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                            detailed_changes.append({
                                "row_id": r_id,
                                "column": c,
                                "original_value": _safe_val(df.loc[idx, c]),
                                "new_value": None,
                                "operation": "Missing Values: Custom Marker",
                                "reason": f"Standardized custom null marker '{df.loc[idx, c]}' to NaN",
                                "status": "Applied",
                            })
                            df.loc[idx, c] = np.nan

    initial_nulls = int(df[target_cols].isna().sum().sum())
    missing_filled = 0
    rows_removed = 0
    cells_changed = cells_marked

    if action == "drop_rows":
        mask = df[target_cols].isna().any(axis=1)
        rows_removed = int(mask.sum())
        cells_changed += rows_removed
        dropped_df = df[mask]
        for idx in dropped_df.index:
            r_id = dropped_df.loc[idx, ROW_ID_COL] if ROW_ID_COL in dropped_df.columns else int(idx) + 1
            null_cols = [c for c in target_cols if pd.isna(dropped_df.loc[idx, c])]
            detailed_changes.append({
                "row_id": r_id,
                "column": "[Row]",
                "original_value": f"Row with missing {', '.join(null_cols)}",
                "new_value": "[Deleted Row]",
                "operation": "Missing Values: Drop Rows",
                "reason": f"Removed row containing missing values in {null_cols}",
                "status": "Deleted",
            })
        df = df[~mask].reset_index(drop=True)

    elif action == "drop_columns":
        drop_list = [c for c in target_cols if df[c].isna().any()]
        for c in drop_list:
            null_cnt = int(df[c].isna().sum())
            detailed_changes.append({
                "row_id": "-",
                "column": c,
                "original_value": f"Column with {null_cnt} missing values",
                "new_value": "[Dropped Column]",
                "operation": "Missing Values: Drop Column",
                "reason": f"Dropped column '{c}' containing {null_cnt} missing values",
                "status": "Deleted",
            })
        cells_changed += len(drop_list)
        df = df.drop(columns=drop_list)

    elif action in ("fill_numeric", "fill_categorical", "fill_constant", "ffill", "bfill"):
        for c in target_cols:
            if c not in df.columns:
                continue
            s = df[c]
            null_mask = s.isna()
            nulls = int(null_mask.sum())
            if nulls == 0:
                continue

            if action == "fill_numeric":
                strategy = params.get("strategy", "median")
                s_num = pd.to_numeric(s, errors="coerce")
                fill_val = s_num.median() if strategy == "median" else s_num.mean()
                if pd.notna(fill_val):
                    for idx in df[null_mask].index:
                        r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                        detailed_changes.append({
                            "row_id": r_id,
                            "column": c,
                            "original_value": None,
                            "new_value": _safe_val(fill_val),
                            "operation": f"Missing Values: Fill ({strategy})",
                            "reason": f"Imputed missing value in '{c}' using {strategy}",
                            "status": "Applied",
                        })
                    df[c] = s.fillna(fill_val)
                    missing_filled += nulls
                    cells_changed += nulls

            elif action == "fill_categorical":
                mode_vals = s.mode(dropna=True)
                if len(mode_vals) > 0:
                    fill_val = mode_vals.iloc[0]
                    for idx in df[null_mask].index:
                        r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                        detailed_changes.append({
                            "row_id": r_id,
                            "column": c,
                            "original_value": None,
                            "new_value": _safe_val(fill_val),
                            "operation": "Missing Values: Fill (mode)",
                            "reason": f"Imputed missing value in '{c}' with mode ('{fill_val}')",
                            "status": "Applied",
                        })
                    df[c] = s.fillna(fill_val)
                    missing_filled += nulls
                    cells_changed += nulls

            elif action == "fill_constant":
                const_val = params.get("value", "")
                if pd.api.types.is_numeric_dtype(s):
                    try:
                        c_val = float(const_val) if "." in str(const_val) else int(const_val)
                    except Exception:
                        c_val = const_val
                else:
                    c_val = const_val

                for idx in df[null_mask].index:
                    r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": None,
                        "new_value": _safe_val(c_val),
                        "operation": "Missing Values: Fill (constant)",
                        "reason": f"Filled missing value in '{c}' with constant '{c_val}'",
                        "status": "Applied",
                    })
                df[c] = s.fillna(c_val)
                missing_filled += nulls
                cells_changed += nulls

            elif action in ("ffill", "bfill"):
                filled_s = s.ffill() if action == "ffill" else s.bfill()
                for idx in df[null_mask].index:
                    if pd.notna(filled_s.loc[idx]):
                        r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                        new_v = filled_s.loc[idx]
                        detailed_changes.append({
                            "row_id": r_id,
                            "column": c,
                            "original_value": None,
                            "new_value": _safe_val(new_v),
                            "operation": f"Missing Values: {action.upper()}",
                            "reason": f"Propagated value using {action}",
                            "status": "Applied",
                        })
                        missing_filled += 1
                        cells_changed += 1
                df[c] = filled_s

    # Status classification
    if cells_changed > 0 or rows_removed > 0:
        status = "Applied"
        reason = f"Applied missing value handling '{action}' on {len(target_cols)} column(s): {cells_changed} cell(s) changed, {rows_removed} row(s) removed"
    else:
        status = "Checked — no change"
        reason = f"Checked {len(target_cols)} column(s) for missing values with action '{action}'; no values required modification"

    issue_detected = f"Detected {initial_nulls} missing cell(s) in {len(target_cols)} column(s)" if initial_nulls > 0 else "No missing values found in checked columns"
    if cells_marked > 0:
        issue_detected += f" ({cells_marked} custom null marker(s) converted to NaN)"

    meta = {
        "operation": "missing_values",
        "name": "Missing Values Handling",
        "action": action,
        "status": status,
        "columns": target_cols,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": rows_removed or (missing_filled + cells_marked),
        "cells_changed": cells_changed,
        "rows_removed": rows_removed,
        "missing_filled": missing_filled,
        "values_affected": cells_changed or missing_filled or cells_marked,
        "cells_marked_from_custom_markers": cells_marked,
        "rows_before": rows_before,
        "rows_after": len(df),
        "cols_before": cols_before,
        "cols_after": len([c for c in df.columns if c != ROW_ID_COL]),
        "reason": reason,
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }
    return df, meta


def op_duplicates(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Handle exact and subset duplicates with complete audit logs."""
    df = df.copy()
    subset = params.get("subset") or params.get("columns") or None
    if subset:
        subset = [c for c in subset if c in df.columns and c != ROW_ID_COL] or None
    else:
        subset = [c for c in df.columns if c != ROW_ID_COL]

    action = params.get("action", "keep_first")  # keep_first, keep_last, remove_all, keep_all
    rows_before = len(df)
    detailed_changes: list[dict[str, Any]] = []

    if action == "keep_all":
        dup_mask = df.duplicated(subset=subset, keep=False)
        dup_count = int(dup_mask.sum())
        for idx in df[dup_mask].index:
            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": "[Row]",
                "original_value": "Duplicate record",
                "new_value": "[Duplicate Flagged (retained)]",
                "operation": "Duplicate Detection",
                "reason": f"Flagged duplicate row based on {subset}; retained per configuration",
                "status": "Flagged",
            })
        status = "Flagged" if dup_count > 0 else "Checked — no change"
        meta = {
            "operation": "duplicates",
            "name": "Duplicate Rows Check",
            "action": "keep_all",
            "status": status,
            "columns": subset,
            "issue_detected": f"Found {dup_count} duplicate rows (keep_all selected)" if dup_count > 0 else "No duplicate rows found",
            "rows_inspected": rows_before,
            "rows_affected": 0,
            "cells_changed": 0,
            "rows_removed": 0,
            "missing_filled": 0,
            "values_affected": 0,
            "duplicates_found": dup_count,
            "rows_before": rows_before,
            "rows_after": len(df),
            "reason": f"Detected {dup_count} duplicate row(s); retained all rows as requested",
            "parameters": params,
            "sample_changes": detailed_changes[:5],
            "detailed_changes": detailed_changes,
        }
        return df, meta

    if action == "keep_first":
        mask_drop = df.duplicated(subset=subset, keep="first")
    elif action == "keep_last":
        mask_drop = df.duplicated(subset=subset, keep="last")
    elif action == "remove_all":
        mask_drop = df.duplicated(subset=subset, keep=False)
    else:
        mask_drop = df.duplicated(subset=subset, keep="first")

    rows_dropped = int(mask_drop.sum())
    dropped_df = df[mask_drop]

    for idx in dropped_df.index:
        r_id = dropped_df.loc[idx, ROW_ID_COL] if ROW_ID_COL in dropped_df.columns else int(idx) + 1
        key_preview = {c: _safe_val(dropped_df.loc[idx, c]) for c in (subset[:4] if subset else [])}
        detailed_changes.append({
            "row_id": r_id,
            "column": "[Row]",
            "original_value": f"Duplicate record ({key_preview})",
            "new_value": "[Deleted Duplicate Row]",
            "operation": "Duplicate Rows Removal",
            "reason": f"Removed duplicate record ({action}) matching key: {subset}",
            "status": "Deleted",
        })

    df = df[~mask_drop].reset_index(drop=True)
    status = "Applied" if rows_dropped > 0 else "Checked — no change"
    issue_detected = f"Detected {rows_dropped} duplicate row(s)" if rows_dropped > 0 else "No duplicate rows found"

    meta = {
        "operation": "duplicates",
        "name": "Duplicate Rows Removal",
        "action": action,
        "status": status,
        "subset": subset,
        "columns": subset,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": rows_dropped,
        "cells_changed": rows_dropped,
        "rows_removed": rows_dropped,
        "missing_filled": 0,
        "values_affected": rows_dropped * len(subset),
        "rows_before": rows_before,
        "rows_after": len(df),
        "reason": f"Removed {rows_dropped} duplicate row(s) ({action}) based on key {subset}" if rows_dropped > 0 else f"Checked duplicates on {subset}; none found",
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }
    return df, meta


def op_text_normalization(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize text and column names with cell-level change tracking."""
    df = df.copy()
    action = params.get("action")  # snake_case_columns, trim_whitespace, normalize_internal_spaces, change_case, replace_values
    raw_cols = params.get("columns") or ([params["column"]] if params.get("column") else text_cols(df))
    target_cols = [c for c in raw_cols if c in df.columns and c != ROW_ID_COL]
    detailed_changes: list[dict[str, Any]] = []
    rows_before = len(df)
    cells_changed = 0

    if action == "snake_case_columns":
        old_cols = [c for c in df.columns if c != ROW_ID_COL]
        new_cols_clean = deduplicate_column_names([snake_case_name(c) for c in old_cols])
        mapping = {}
        for old, new in zip(old_cols, new_cols_clean):
            if old != new:
                mapping[old] = new
                detailed_changes.append({
                    "row_id": "-",
                    "column": old,
                    "original_value": old,
                    "new_value": new,
                    "operation": "Column Name Normalization",
                    "reason": f"Standardized column '{old}' to snake_case '{new}'",
                    "status": "Applied",
                })
        cells_changed = len(mapping)
        if ROW_ID_COL in df.columns:
            df.columns = [mapping.get(c, c) if c != ROW_ID_COL else ROW_ID_COL for c in df.columns]
        else:
            df.columns = [mapping.get(c, c) for c in df.columns]

        status = "Applied" if cells_changed > 0 else "Checked — no change"
        return df, {
            "operation": "text_normalization",
            "name": "Column Name Normalization",
            "action": "snake_case_columns",
            "status": status,
            "columns": list(mapping.keys()),
            "issue_detected": f"Found {cells_changed} non-snake-case column names" if cells_changed > 0 else "All column names are already clean snake_case",
            "rows_inspected": rows_before,
            "rows_affected": 0,
            "cells_changed": cells_changed,
            "rows_removed": 0,
            "missing_filled": 0,
            "values_affected": cells_changed,
            "reason": f"Normalized {cells_changed} column name(s) to snake_case" if cells_changed > 0 else "All column names already conform to snake_case",
            "parameters": params,
            "sample_changes": detailed_changes[:5],
            "detailed_changes": detailed_changes,
        }

    for c in target_cols:
        s = df[c]
        non_null_mask = s.notna()

        if action == "trim_whitespace":
            for idx in df[non_null_mask].index:
                val = str(df.loc[idx, c])
                trimmed = val.strip()
                if val != trimmed:
                    r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": val,
                        "new_value": trimmed,
                        "operation": "Whitespace Trimming",
                        "reason": f"Trimmed leading/trailing whitespace in '{c}'",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = trimmed

        elif action == "normalize_internal_spaces":
            for idx in df[non_null_mask].index:
                val = str(df.loc[idx, c])
                normed = re.sub(r"\s+", " ", val).strip()
                if val != normed:
                    r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": val,
                        "new_value": normed,
                        "operation": "Whitespace Normalization",
                        "reason": f"Normalized internal spacing in '{c}'",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = normed

        elif action == "change_case":
            case = params.get("case", "lower")
            fn = {"lower": str.lower, "upper": str.upper, "title": str.title}.get(case, str.lower)
            for idx in df[non_null_mask].index:
                val = str(df.loc[idx, c])
                converted = fn(val)
                if val != converted:
                    r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": val,
                        "new_value": converted,
                        "operation": f"Text Casing ({case})",
                        "reason": f"Converted '{c}' to {case}",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = converted

        elif action == "replace_values":
            mapping = params.get("mapping") or {}
            for idx in df[non_null_mask].index:
                val = df.loc[idx, c]
                if val in mapping:
                    new_val = mapping[val]
                    r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": _safe_val(val),
                        "new_value": _safe_val(new_val),
                        "operation": "Category Standardization",
                        "reason": f"Standardized near-duplicate in '{c}' ('{val}' → '{new_val}')",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = new_val

    status = "Applied" if cells_changed > 0 else "Checked — no change"
    issue_detected = f"Detected {cells_changed} text formatting issue(s) in {len(target_cols)} column(s)" if cells_changed > 0 else f"No text formatting changes needed for '{action}' in {len(target_cols)} column(s)"

    return df, {
        "operation": "text_normalization",
        "name": f"Text Normalization ({action})",
        "action": action,
        "status": status,
        "columns": target_cols,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": cells_changed,
        "cells_changed": cells_changed,
        "rows_removed": 0,
        "missing_filled": 0,
        "values_affected": cells_changed,
        "reason": f"Applied '{action}' on {len(target_cols)} column(s): {cells_changed} value(s) standardized" if cells_changed > 0 else f"Checked '{action}' on {len(target_cols)} column(s); all values already standardized",
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }


def op_type_conversion(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Convert data types with individual cell audit tracking and failed conversion reporting."""
    df = df.copy()
    raw_cols = params.get("columns") or ([params["column"]] if params.get("column") else [])
    target_cols = [c for c in raw_cols if c in df.columns and c != ROW_ID_COL]
    target_type = params.get("target_type") or params.get("dtype")
    date_format = params.get("date_format")
    strip_symbols = params.get("strip_currency", True)

    detailed_changes: list[dict[str, Any]] = []
    failed_counts: dict[str, int] = {}
    rows_before = len(df)
    cells_changed = 0

    for c in target_cols:
        s = df[c]
        non_null_mask = s.notna()
        if not non_null_mask.any():
            continue

        failed_in_col = 0
        if target_type in ("int", "integer"):
            for idx in df[non_null_mask].index:
                val = str(df.loc[idx, c])
                cleaned = re.sub(CURRENCY_CHARS, "", val) if strip_symbols else val
                cleaned = re.sub(r"^\((.*)\)$", r"-\1", cleaned).strip()
                r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                try:
                    num_val = int(round(float(cleaned)))
                    if _are_different(df.loc[idx, c], num_val):
                        detailed_changes.append({
                            "row_id": r_id,
                            "column": c,
                            "original_value": _safe_val(df.loc[idx, c]),
                            "new_value": num_val,
                            "operation": "Type Conversion (int)",
                            "reason": f"Converted '{df.loc[idx, c]}' to integer",
                            "status": "Applied",
                        })
                        cells_changed += 1
                    df.loc[idx, c] = num_val
                except Exception:
                    failed_in_col += 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": _safe_val(df.loc[idx, c]),
                        "new_value": None,
                        "operation": "Type Conversion (int)",
                        "reason": f"Coerced unparseable value '{df.loc[idx, c]}' to null during int conversion",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = np.nan
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

        elif target_type in ("float", "numeric"):
            for idx in df[non_null_mask].index:
                val = str(df.loc[idx, c])
                cleaned = re.sub(CURRENCY_CHARS, "", val) if strip_symbols else val
                cleaned = re.sub(r"^\((.*)\)$", r"-\1", cleaned).strip()
                r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                try:
                    flt_val = float(cleaned)
                    if _are_different(df.loc[idx, c], flt_val):
                        detailed_changes.append({
                            "row_id": r_id,
                            "column": c,
                            "original_value": _safe_val(df.loc[idx, c]),
                            "new_value": round(flt_val, 4),
                            "operation": "Type Conversion (float)",
                            "reason": f"Parsed currency/numeric '{df.loc[idx, c]}' to float",
                            "status": "Applied",
                        })
                        cells_changed += 1
                    df.loc[idx, c] = flt_val
                except Exception:
                    failed_in_col += 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": _safe_val(df.loc[idx, c]),
                        "new_value": None,
                        "operation": "Type Conversion (float)",
                        "reason": f"Coerced unparseable value '{df.loc[idx, c]}' to null during float conversion",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = np.nan
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)

        elif target_type in ("datetime", "date"):
            for idx in df[non_null_mask].index:
                val = str(df.loc[idx, c])
                r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                try:
                    if date_format:
                        dt_val = pd.to_datetime(val, format=date_format, errors="raise")
                    else:
                        dt_val = pd.to_datetime(val, errors="raise", format="mixed")
                    if _are_different(df.loc[idx, c], dt_val):
                        detailed_changes.append({
                            "row_id": r_id,
                            "column": c,
                            "original_value": val,
                            "new_value": dt_val.isoformat(),
                            "operation": "Type Conversion (datetime)",
                            "reason": f"Parsed date string '{val}' to datetime",
                            "status": "Applied",
                        })
                        cells_changed += 1
                    df.loc[idx, c] = dt_val
                except Exception:
                    failed_in_col += 1
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": val,
                        "new_value": None,
                        "operation": "Type Conversion (datetime)",
                        "reason": f"Coerced unparseable date '{val}' to null",
                        "status": "Applied",
                    })
                    cells_changed += 1
                    df.loc[idx, c] = pd.NaT
            df[c] = pd.to_datetime(df[c], errors="coerce")

        elif target_type in ("bool", "boolean"):
            def _to_bool(x):
                if pd.isna(x):
                    return None
                val = str(x).strip().lower()
                if val in ("1", "true", "yes", "t", "y"):
                    return True
                if val in ("0", "false", "no", "f", "n"):
                    return False
                return None

            for idx in df[non_null_mask].index:
                b_val = _to_bool(df.loc[idx, c])
                r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                if _are_different(df.loc[idx, c], b_val):
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": _safe_val(df.loc[idx, c]),
                        "new_value": b_val,
                        "operation": "Type Conversion (boolean)",
                        "reason": f"Standardized boolean representation '{df.loc[idx, c]}' → {b_val}",
                        "status": "Applied",
                    })
                    cells_changed += 1
                df.loc[idx, c] = b_val

        elif target_type in ("str", "string"):
            for idx in df[non_null_mask].index:
                s_val = str(df.loc[idx, c])
                r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
                if _are_different(df.loc[idx, c], s_val):
                    detailed_changes.append({
                        "row_id": r_id,
                        "column": c,
                        "original_value": _safe_val(df.loc[idx, c]),
                        "new_value": s_val,
                        "operation": "Type Conversion (string)",
                        "reason": f"Cast to string with preserved leading zeros",
                        "status": "Applied",
                    })
                    cells_changed += 1
            df[c] = df[c].astype("string").astype(object).where(df[c].notna(), None)

        failed_counts[c] = failed_in_col

    status = "Applied" if cells_changed > 0 else "Checked — no change"
    total_fails = sum(failed_counts.values())
    issue_detected = f"Found {cells_changed} values needing type conversion in {len(target_cols)} column(s)" if cells_changed > 0 else f"All checked values already conform to '{target_type}'"
    if total_fails > 0:
        issue_detected += f" ({total_fails} unparseable values coerced to null)"

    return df, {
        "operation": "type_conversion",
        "name": f"Data Type Conversion ({target_type})",
        "target_type": target_type,
        "status": status,
        "columns": target_cols,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": cells_changed,
        "cells_changed": cells_changed,
        "rows_removed": 0,
        "missing_filled": 0,
        "values_affected": cells_changed,
        "failed_conversions": failed_counts,
        "reason": f"Converted {len(target_cols)} column(s) to '{target_type}': {cells_changed} cells transformed" if cells_changed > 0 else f"Checked {len(target_cols)} column(s) for conversion to '{target_type}'; no changes needed",
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }


def op_validation_rules(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply business validation rules with strict distinction between Flagged, Applied, and Dropped."""
    df = df.copy()
    col = params.get("column")
    rule_type = params.get("rule_type")
    action = params.get("action", "flag")  # flag, drop_rows, replace
    replacement_value = params.get("replacement_value", None)
    rows_before = len(df)

    if not col or col not in df.columns:
        raise CleaningEngineError(f"Validation rule requires a valid column. Found: {col}")

    s = df[col]
    invalid_mask = pd.Series(False, index=df.index)

    if rule_type == "numeric_range":
        s_num = pd.to_numeric(s, errors="coerce")
        min_v = params.get("min")
        max_v = params.get("max")
        if min_v is not None:
            invalid_mask |= (s_num < float(min_v))
        if max_v is not None:
            invalid_mask |= (s_num > float(max_v))
        invalid_mask |= (s.notna() & s_num.isna())

    elif rule_type == "non_negative":
        s_num = pd.to_numeric(s, errors="coerce")
        invalid_mask = (s_num < 0) | (s.notna() & s_num.isna())

    elif rule_type == "allowed_values":
        allowed = set(params.get("allowed_values") or [])
        if allowed:
            invalid_mask = s.notna() & (~s.astype(str).isin([str(a) for a in allowed]))

    elif rule_type == "required":
        invalid_mask = s.isna() | (s.astype(str).str.strip() == "")

    elif rule_type in ("regex", "email"):
        rx_pattern = r"^[\w.+-]+@[\w-]+\.[\w.-]+$" if rule_type == "email" else params.get("pattern", ".*")
        rx = re.compile(rx_pattern)
        invalid_mask = s.notna() & (~s.astype(str).map(lambda x: bool(rx.match(x))))

    elif rule_type == "date_range":
        s_date = pd.to_datetime(s, errors="coerce")
        min_d = pd.to_datetime(params.get("min_date")) if params.get("min_date") else None
        max_d = pd.to_datetime(params.get("max_date")) if params.get("max_date") else None
        if min_d:
            invalid_mask |= (s_date < min_d)
        if max_d:
            invalid_mask |= (s_date > max_d)

    invalid_count = int(invalid_mask.sum())
    detailed_changes: list[dict[str, Any]] = []
    rows_removed = 0
    cells_changed = 0

    if action == "flag":
        status = "Flagged" if invalid_count > 0 else "Checked — no change"
        for idx in df[invalid_mask].index:
            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": col,
                "original_value": _safe_val(df.loc[idx, col]),
                "new_value": "[Flagged Violation (unchanged)]",
                "operation": f"Validation Rule ({rule_type})",
                "reason": f"Value violated business rule '{rule_type}'; flagged without modification",
                "status": "Flagged",
            })
        reason = f"Evaluated business rule '{rule_type}' on '{col}'; flagged {invalid_count} violation(s)"

    elif action == "drop_rows":
        rows_removed = invalid_count
        cells_changed = invalid_count
        status = "Applied" if invalid_count > 0 else "Checked — no change"
        dropped_df = df[invalid_mask]
        for idx in dropped_df.index:
            r_id = dropped_df.loc[idx, ROW_ID_COL] if ROW_ID_COL in dropped_df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": "[Row]",
                "original_value": f"Violated rule '{rule_type}' in '{col}' ({_safe_val(dropped_df.loc[idx, col])})",
                "new_value": "[Deleted Row]",
                "operation": f"Validation Rule ({rule_type})",
                "reason": f"Dropped row violating rule '{rule_type}' on '{col}'",
                "status": "Deleted",
            })
        df = df[~invalid_mask].reset_index(drop=True)
        reason = f"Evaluated business rule '{rule_type}' on '{col}'; dropped {invalid_count} violating row(s)"

    elif action == "replace":
        cells_changed = invalid_count
        status = "Applied" if invalid_count > 0 else "Checked — no change"
        for idx in df[invalid_mask].index:
            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": col,
                "original_value": _safe_val(df.loc[idx, col]),
                "new_value": _safe_val(replacement_value),
                "operation": f"Validation Rule ({rule_type})",
                "reason": f"Replaced invalid value violating rule '{rule_type}' with '{replacement_value}'",
                "status": "Applied",
            })
            df.loc[idx, col] = replacement_value
        reason = f"Evaluated business rule '{rule_type}' on '{col}'; replaced {invalid_count} violating cell(s)"

    issue_detected = f"Found {invalid_count} violation(s) of rule '{rule_type}' on '{col}'" if invalid_count > 0 else f"No violations found for rule '{rule_type}' on '{col}'"

    meta = {
        "operation": "validation_rule",
        "name": f"Validation Rule ({rule_type})",
        "column": col,
        "columns": [col],
        "rule_type": rule_type,
        "action": action,
        "status": status,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": invalid_count,
        "cells_changed": cells_changed,
        "rows_removed": rows_removed,
        "missing_filled": 0,
        "violations_found": invalid_count,
        "values_affected": cells_changed,
        "rows_before": rows_before,
        "rows_after": len(df),
        "reason": reason,
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }
    return df, meta


def op_outliers(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Detect and treat outliers via IQR or Z-score without misrepresenting flagged values as changed."""
    df = df.copy()
    col = params.get("column")
    if not col or col not in df.columns:
        raise CleaningEngineError(f"Outlier operation requires a valid column. Found: {col}")

    s = pd.to_numeric(df[col], errors="coerce")
    method = params.get("method", "iqr")  # iqr, zscore
    action = params.get("action", "flag")  # flag, cap, drop_rows
    factor = float(params.get("factor", 1.5))
    rows_before = len(df)
    detailed_changes: list[dict[str, Any]] = []

    v = s.dropna()
    if len(v) < 4:
        return df, {
            "operation": "outliers",
            "name": f"Outlier Check ({method.upper()})",
            "column": col,
            "columns": [col],
            "status": "Checked — no change",
            "issue_detected": "Not enough numeric values to calculate outlier bounds",
            "rows_inspected": rows_before,
            "rows_affected": 0,
            "cells_changed": 0,
            "rows_removed": 0,
            "missing_filled": 0,
            "values_affected": 0,
            "outliers_found": 0,
            "reason": "Not enough numeric values to evaluate outliers",
            "parameters": params,
            "sample_changes": [],
            "detailed_changes": [],
        }

    if method == "zscore":
        mean_v, std_v = v.mean(), v.std()
        thresh = float(params.get("threshold", 3.0))
        lo, hi = mean_v - thresh * std_v, mean_v + thresh * std_v
    else:  # iqr
        q1, q3 = v.quantile(0.25), v.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - factor * iqr, q3 + factor * iqr

    outlier_mask = (s < lo) | (s > hi)
    outlier_count = int(outlier_mask.sum())
    cells_changed = 0
    rows_removed = 0

    if action == "flag":
        status = "Flagged" if outlier_count > 0 else "Checked — no change"
        for idx in df[outlier_mask].index:
            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": col,
                "original_value": _safe_val(df.loc[idx, col]),
                "new_value": "[Flagged Outlier (unchanged)]",
                "operation": f"Outlier Detection ({method.upper()})",
                "reason": f"Outlier detected via {method.upper()} outside bounds [{round(lo, 2)}, {round(hi, 2)}]; value retained",
                "status": "Flagged",
            })
        reason = f"Detected {outlier_count} outlier(s) using {method.upper()} in '{col}' (bounds [{round(lo,2)}, {round(hi,2)}]); flagged without modifying data"

    elif action == "cap":
        status = "Applied" if outlier_count > 0 else "Checked — no change"
        cells_changed = outlier_count
        for idx in df[outlier_mask].index:
            old_v = df.loc[idx, col]
            new_v = lo if s.loc[idx] < lo else hi
            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": col,
                "original_value": _safe_val(old_v),
                "new_value": round(float(new_v), 4),
                "operation": f"Outlier Capping ({method.upper()})",
                "reason": f"Capped outlier from {_safe_val(old_v)} to bound {round(float(new_v), 2)}",
                "status": "Applied",
            })
        df[col] = s.clip(lo, hi)
        reason = f"Detected {outlier_count} outlier(s) using {method.upper()} in '{col}'; capped values to [{round(lo,2)}, {round(hi,2)}]"

    elif action == "drop_rows":
        status = "Applied" if outlier_count > 0 else "Checked — no change"
        rows_removed = outlier_count
        cells_changed = outlier_count
        dropped_df = df[outlier_mask]
        for idx in dropped_df.index:
            r_id = dropped_df.loc[idx, ROW_ID_COL] if ROW_ID_COL in dropped_df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": "[Row]",
                "original_value": f"Row with outlier in '{col}' ({_safe_val(dropped_df.loc[idx, col])})",
                "new_value": "[Deleted Row]",
                "operation": f"Outlier Removal ({method.upper()})",
                "reason": f"Dropped row with extreme outlier in '{col}'",
                "status": "Deleted",
            })
        df = df[~outlier_mask].reset_index(drop=True)
        reason = f"Detected {outlier_count} outlier(s) using {method.upper()} in '{col}'; dropped {outlier_count} outlier row(s)"

    issue_detected = f"Found {outlier_count} statistical outlier(s) in '{col}' outside [{round(lo,2)}, {round(hi,2)}]" if outlier_count > 0 else f"No outliers found in '{col}' using {method.upper()}"

    meta = {
        "operation": "outliers",
        "name": f"Outlier Handling ({method.upper()})",
        "column": col,
        "columns": [col],
        "method": method,
        "action": action,
        "status": status,
        "bounds": [round(float(lo), 4), round(float(hi), 4)],
        "outliers_found": outlier_count,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": outlier_count,
        "cells_changed": cells_changed,
        "rows_removed": rows_removed,
        "missing_filled": 0,
        "values_affected": cells_changed,
        "rows_before": rows_before,
        "rows_after": len(df),
        "reason": reason,
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }
    return df, meta


def op_structural(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Remove empty rows/cols or constant columns with full audit recording."""
    df = df.copy()
    action = params.get("action")  # drop_empty_rows, drop_empty_cols, drop_constant_cols
    rows_before = len(df)
    cols_before = len([c for c in df.columns if c != ROW_ID_COL])
    detailed_changes: list[dict[str, Any]] = []
    affected = 0
    rows_removed = 0

    valid_cols = [c for c in df.columns if c != ROW_ID_COL]

    if action == "drop_empty_rows":
        empty_mask = df[valid_cols].isna().all(axis=1)
        affected = int(empty_mask.sum())
        rows_removed = affected
        dropped_df = df[empty_mask]
        for idx in dropped_df.index:
            r_id = dropped_df.loc[idx, ROW_ID_COL] if ROW_ID_COL in dropped_df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": "[Row]",
                "original_value": "Completely empty row",
                "new_value": "[Deleted Row]",
                "operation": "Structural: Empty Rows",
                "reason": "Removed completely empty row",
                "status": "Deleted",
            })
        df = df[~empty_mask].reset_index(drop=True)

    elif action == "drop_empty_cols":
        empty_cols = [c for c in valid_cols if df[c].isna().all()]
        affected = len(empty_cols)
        for c in empty_cols:
            detailed_changes.append({
                "row_id": "-",
                "column": c,
                "original_value": "Entirely empty column",
                "new_value": "[Dropped Column]",
                "operation": "Structural: Empty Columns",
                "reason": f"Dropped completely empty column '{c}'",
                "status": "Deleted",
            })
        df = df.drop(columns=empty_cols)

    elif action == "drop_constant_cols":
        const_cols = [c for c in valid_cols if df[c].nunique(dropna=True) <= 1 and df[c].notna().any()]
        affected = len(const_cols)
        for c in const_cols:
            val = df[c].dropna().iloc[0] if not df[c].dropna().empty else None
            detailed_changes.append({
                "row_id": "-",
                "column": c,
                "original_value": f"Constant value '{_safe_val(val)}'",
                "new_value": "[Dropped Column]",
                "operation": "Structural: Constant Columns",
                "reason": f"Dropped column '{c}' with single constant value '{val}'",
                "status": "Deleted",
            })
        df = df.drop(columns=const_cols)

    status = "Applied" if affected > 0 else "Checked — no change"
    issue_detected = f"Found {affected} structural issue(s) ({action})" if affected > 0 else f"No structural issues found for '{action}'"

    return df, {
        "operation": "structural",
        "name": f"Structural Cleanup ({action})",
        "action": action,
        "status": status,
        "columns": valid_cols,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": rows_removed or affected,
        "cells_changed": affected,
        "rows_removed": rows_removed,
        "missing_filled": 0,
        "values_affected": affected,
        "rows_before": rows_before,
        "rows_after": len(df),
        "cols_before": cols_before,
        "cols_after": len([c for c in df.columns if c != ROW_ID_COL]),
        "reason": f"Executed structural cleanup '{action}': affected {affected}" if affected > 0 else f"Checked structural condition '{action}'; no columns/rows needed removal",
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }


def op_mask_pii(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Mask PII columns using keyed HMAC or redaction, protecting sensitive information."""
    df = df.copy()
    raw_cols = params.get("columns") or ([params["column"]] if params.get("column") else [])
    target_cols = [c for c in raw_cols if c in df.columns and c != ROW_ID_COL]
    mode = params.get("mode", "hash")
    key = settings.JWT_SECRET.encode()
    rows_before = len(df)
    detailed_changes: list[dict[str, Any]] = []
    cells_changed = 0

    def mask_one(x: Any) -> Any:
        if pd.isna(x):
            return x
        s = str(x)
        if mode == "hash":
            return hmac.new(key, s.encode(), hashlib.sha256).hexdigest()[:16]
        if "@" in s:
            u, d = s.split("@", 1)
            return u[:1] + "***@" + d
        return "*" * max(len(s) - 2, 0) + s[-2:]

    def safe_mask_preview(x: Any) -> str:
        """Never expose sensitive data unnecessarily in audit table."""
        if pd.isna(x):
            return "[Empty]"
        s = str(x)
        if "@" in s:
            u, d = s.split("@", 1)
            return u[:1] + "***@" + d
        if len(s) >= 6:
            return s[:2] + "****" + s[-2:]
        return "[Sensitive PII]"

    for c in target_cols:
        non_null_mask = df[c].notna()
        for idx in df[non_null_mask].index:
            old_val = df.loc[idx, c]
            new_val = mask_one(old_val)
            r_id = df.loc[idx, ROW_ID_COL] if ROW_ID_COL in df.columns else int(idx) + 1
            detailed_changes.append({
                "row_id": r_id,
                "column": c,
                "original_value": safe_mask_preview(old_val),
                "new_value": new_val,
                "operation": f"PII Masking ({mode})",
                "reason": f"Masked sensitive PII column '{c}' using keyed {mode}",
                "status": "Applied",
            })
            cells_changed += 1
            df.loc[idx, c] = new_val

    status = "Applied" if cells_changed > 0 else "Checked — no change"
    issue_detected = f"Detected {cells_changed} sensitive PII values in {len(target_cols)} column(s)" if cells_changed > 0 else "No PII values found in target column(s)"

    return df, {
        "operation": "mask_pii",
        "name": f"PII Protection ({mode})",
        "mode": mode,
        "status": status,
        "columns": target_cols,
        "issue_detected": issue_detected,
        "rows_inspected": rows_before,
        "rows_affected": cells_changed,
        "cells_changed": cells_changed,
        "rows_removed": 0,
        "missing_filled": 0,
        "values_affected": cells_changed,
        "rows_before": rows_before,
        "rows_after": len(df),
        "reason": f"Masked {cells_changed} sensitive value(s) in {len(target_cols)} column(s) via {mode}",
        "parameters": params,
        "sample_changes": detailed_changes[:5],
        "detailed_changes": detailed_changes,
    }


# Map of all operations
CLEANING_DISPATCH = {
    "missing_values": op_missing_values,
    "drop_nulls": op_missing_values,
    "fill_nulls": op_missing_values,
    "duplicates": op_duplicates,
    "drop_duplicates": op_duplicates,
    "text_normalization": op_text_normalization,
    "trim": op_text_normalization,
    "change_case": op_text_normalization,
    "snake_case": op_text_normalization,
    "replace_values": op_text_normalization,
    "type_conversion": op_type_conversion,
    "cast": op_type_conversion,
    "strip_currency": op_type_conversion,
    "validation_rules": op_validation_rules,
    "validation_rule": op_validation_rules,
    "outliers": op_outliers,
    "clip_outliers": op_outliers,
    "structural": op_structural,
    "mask_pii": op_mask_pii,
}


def normalize_legacy_op(op: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Ensure backward-compatibility with older Datapilot step definitions."""
    p = dict(params)
    if op == "drop_nulls":
        return "missing_values", {**p, "action": "drop_rows"}
    if op == "fill_nulls":
        strat = p.get("strategy", "value")
        act = "fill_numeric" if strat in ("mean", "median") else "fill_categorical" if strat == "mode" else "fill_constant" if strat == "value" else strat
        return "missing_values", {**p, "action": act}
    if op == "drop_duplicates":
        return "duplicates", {**p, "action": "keep_first", "subset": p.get("columns")}
    if op == "trim":
        return "text_normalization", {**p, "action": "trim_whitespace"}
    if op == "change_case":
        return "text_normalization", {**p, "action": "change_case"}
    if op == "replace_values":
        return "text_normalization", {**p, "action": "replace_values"}
    if op == "cast":
        return "type_conversion", {**p, "target_type": p.get("dtype")}
    if op == "strip_currency":
        return "type_conversion", {**p, "target_type": "float", "strip_currency": True}
    if op == "clip_outliers":
        col = p.get("columns", [None])[0] if p.get("columns") else p.get("column")
        return "outliers", {**p, "column": col, "action": "cap"}
    return op, p


def execute_step(df: pd.DataFrame, step: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute a single cleaning step deterministically."""
    raw_op = step.get("op", "")
    params = step.get("params") or {}
    op_name, norm_params = normalize_legacy_op(raw_op, params)

    fn = CLEANING_DISPATCH.get(op_name)
    if not fn:
        raise CleaningEngineError(f"Unsupported cleaning operation '{raw_op}'.")

    return fn(df, norm_params)


# ── Quality Profile Comparison ────────────────────────────────────────────────

def compute_quality_comparison(
    original_df: pd.DataFrame,
    cleaned_df: pd.DataFrame,
    detailed_changes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compute before-and-after data quality metrics per column according to Section 5."""
    orig_cols = [c for c in original_df.columns if c != ROW_ID_COL]
    clean_cols = [c for c in cleaned_df.columns if c != ROW_ID_COL]
    all_cols = sorted(set(orig_cols + clean_cols))

    # Count changes per column from audit log
    changes_by_col: dict[str, int] = {}
    for ch in detailed_changes:
        c = ch.get("column")
        if c and c != "[Row]":
            changes_by_col[c] = changes_by_col.get(c, 0) + (1 if ch.get("status") == "Applied" else 0)

    comparison = []
    for c in all_cols:
        in_orig = c in original_df.columns
        in_clean = c in cleaned_df.columns

        if not in_clean:
            # Column was dropped
            comparison.append({
                "column": c,
                "dtype_before": str(original_df[c].dtype) if in_orig else "-",
                "dtype_after": "[Dropped]",
                "missing_before": int(original_df[c].isna().sum()) if in_orig else 0,
                "missing_after": 0,
                "missing_diff": -(int(original_df[c].isna().sum()) if in_orig else 0),
                "invalid_before": 0,
                "invalid_after": 0,
                "outliers_before": 0,
                "outliers_after": 0,
                "changed_values": changes_by_col.get(c, 0),
                "unresolved_issues": 0,
                "status": "dropped",
            })
            continue

        s_orig = original_df[c] if in_orig else pd.Series(dtype=object)
        s_clean = cleaned_df[c]

        miss_before = int(s_orig.isna().sum()) if in_orig else 0
        miss_after = int(s_clean.isna().sum())
        miss_diff = miss_after - miss_before

        dtype_before = str(s_orig.dtype) if in_orig else "-"
        dtype_after = str(s_clean.dtype)

        # Outliers before/after for numeric columns
        outliers_before = 0
        outliers_after = 0
        if pd.api.types.is_numeric_dtype(s_orig) and len(s_orig.dropna()) >= 4:
            q1, q3 = s_orig.quantile(0.25), s_orig.quantile(0.75)
            iqr = q3 - q1
            outliers_before = int(((s_orig < (q1 - 1.5 * iqr)) | (s_orig > (q3 + 1.5 * iqr))).sum())
        if pd.api.types.is_numeric_dtype(s_clean) and len(s_clean.dropna()) >= 4:
            q1, q3 = s_clean.quantile(0.25), s_clean.quantile(0.75)
            iqr = q3 - q1
            outliers_after = int(((s_clean < (q1 - 1.5 * iqr)) | (s_clean > (q3 + 1.5 * iqr))).sum())

        unresolved = miss_after + outliers_after
        status = "improved" if (miss_after < miss_before or outliers_after < outliers_before or dtype_before != dtype_after) else "unchanged"

        comparison.append({
            "column": c,
            "dtype_before": dtype_before,
            "dtype_after": dtype_after,
            "missing_before": miss_before,
            "missing_after": miss_after,
            "missing_diff": miss_diff,
            "invalid_before": 0,
            "invalid_after": 0,
            "outliers_before": outliers_before,
            "outliers_after": outliers_after,
            "changed_values": changes_by_col.get(c, 0),
            "unresolved_issues": unresolved,
            "status": status,
        })

    return comparison


# ── Recipe Execution Engine ───────────────────────────────────────────────────

def execute_recipe(
    df_original: pd.DataFrame,
    steps: list[dict[str, Any]],
    dataset_name: str = "dataset"
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Execute an ordered series of cleaning operations starting from original DataFrame with full audit instrumentation."""
    start_time = time.time()
    start_iso = _now_iso()

    # Assign stable internal row identifiers (1-indexed integers)
    current_df = df_original.copy()
    current_df[ROW_ID_COL] = list(range(1, len(current_df) + 1))

    logs: list[dict[str, Any]] = []
    all_detailed_changes: list[dict[str, Any]] = []

    rows_init = len(df_original)
    cols_init = len([c for c in df_original.columns if c != ROW_ID_COL])
    nulls_init = int(df_original.isna().sum().sum())
    dups_init = int(df_original.duplicated().sum())

    duplicate_rows_removed = 0
    missing_values_filled = 0
    values_standardized = 0
    type_conversions_performed = 0
    invalid_corrected_or_removed = 0
    outliers_flagged = 0
    outliers_capped = 0
    outliers_removed = 0

    applied_count = 0
    checked_no_change_count = 0
    flagged_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, step in enumerate(steps, 1):
        step_copy = dict(step)
        op_id = step_copy.get("id") or f"op_{idx}"

        # Check if step is skipped
        is_skipped = step_copy.get("skipped", False) or step_copy.get("params", {}).get("action") == "skip"
        if is_skipped:
            skipped_log = {
                "op_id": op_id,
                "order": idx,
                "name": step_copy.get("op", "Operation"),
                "operation": step_copy.get("op", "unknown"),
                "status": "Skipped",
                "columns": step_copy.get("params", {}).get("columns", []),
                "issue_detected": "User opted to skip this operation",
                "rows_inspected": len(current_df),
                "rows_affected": 0,
                "cells_changed": 0,
                "rows_removed": 0,
                "missing_filled": 0,
                "values_affected": 0,
                "parameters": step_copy.get("params", {}),
                "reason": "Operation skipped by user configuration",
                "timestamp": _now_iso(),
                "sample_changes": [],
                "detailed_changes": [],
            }
            logs.append(skipped_log)
            skipped_count += 1
            continue

        try:
            current_df, step_meta = execute_step(current_df, step_copy)
            step_meta["op_id"] = op_id
            step_meta["order"] = idx
            step_meta["timestamp"] = _now_iso()

            # Tally metrics
            st = step_meta.get("status", "Applied")
            if st == "Applied":
                applied_count += 1
            elif st == "Checked — no change":
                checked_no_change_count += 1
            elif st == "Flagged":
                flagged_count += 1

            op_type = step_meta.get("operation")
            act = step_meta.get("action")

            if op_type == "duplicates":
                duplicate_rows_removed += step_meta.get("rows_removed", 0)
            elif op_type == "missing_values":
                missing_values_filled += step_meta.get("missing_filled", 0)
            elif op_type == "text_normalization":
                values_standardized += step_meta.get("cells_changed", 0)
            elif op_type == "type_conversion":
                type_conversions_performed += 1
                if step_meta.get("cells_changed", 0) > 0:
                    values_standardized += step_meta.get("cells_changed", 0)
            elif op_type == "validation_rule":
                invalid_corrected_or_removed += step_meta.get("cells_changed", 0)
            elif op_type == "outliers":
                if act == "flag":
                    outliers_flagged += step_meta.get("outliers_found", 0)
                elif act == "cap":
                    outliers_capped += step_meta.get("cells_changed", 0)
                elif act == "drop_rows":
                    outliers_removed += step_meta.get("rows_removed", 0)

            step_changes = step_meta.get("detailed_changes", [])
            for ch in step_changes:
                ch["op_id"] = op_id
            all_detailed_changes.extend(step_changes)

            logs.append(step_meta)

        except Exception as e:
            failed_count += 1
            failed_log = {
                "op_id": op_id,
                "order": idx,
                "name": step_copy.get("op", "Operation"),
                "operation": step_copy.get("op", "unknown"),
                "status": "Failed",
                "columns": step_copy.get("params", {}).get("columns", []),
                "issue_detected": f"Operation encountered an error: {str(e)}",
                "rows_inspected": len(current_df),
                "rows_affected": 0,
                "cells_changed": 0,
                "rows_removed": 0,
                "missing_filled": 0,
                "values_affected": 0,
                "parameters": step_copy.get("params", {}),
                "reason": f"Execution failed: {str(e)}",
                "timestamp": _now_iso(),
                "error": str(e),
                "sample_changes": [],
                "detailed_changes": [],
            }
            logs.append(failed_log)

    duration = round(time.time() - start_time, 3)

    # Clean DataFrame to return (strip internal tracking column)
    final_cleaned_df = current_df.drop(columns=[ROW_ID_COL]) if ROW_ID_COL in current_df.columns else current_df.copy()

    rows_final = len(final_cleaned_df)
    cols_final = final_cleaned_df.shape[1]
    nulls_final = int(final_cleaned_df.isna().sum().sum())
    dups_final = int(final_cleaned_df.duplicated().sum())

    # Build unresolved issues list
    unresolved: list[str] = []
    if nulls_final > 0:
        unresolved.append(f"{nulls_final} missing value(s) remain in cleaned dataset.")
    if dups_final > 0:
        unresolved.append(f"{dups_final} duplicate row(s) remain in cleaned dataset.")
    if outliers_flagged > 0:
        unresolved.append(f"{outliers_flagged} flagged outlier(s) were retained without modifications.")
    if failed_count > 0:
        unresolved.append(f"{failed_count} cleaning operation(s) failed during execution.")

    # Quality comparison
    quality_comp = compute_quality_comparison(df_original, final_cleaned_df, all_detailed_changes)

    # Timeline generation
    timeline: list[dict[str, Any]] = [
        {
            "id": "t_0",
            "order": 0,
            "title": "File Parsed Successfully",
            "description": f"Loaded source data ({rows_init} rows, {cols_init} columns).",
            "status": "Completed",
            "timestamp": start_iso,
        }
    ]
    for idx, l in enumerate(logs, 1):
        timeline.append({
            "id": f"t_{idx}",
            "order": idx,
            "title": l.get("name") or l.get("operation"),
            "description": l.get("reason", ""),
            "status": l.get("status", "Applied"),
            "rows_affected": l.get("rows_affected", 0),
            "cells_changed": l.get("cells_changed", 0),
            "timestamp": l.get("timestamp", _now_iso()),
        })
    timeline.append({
        "id": f"t_{len(logs)+1}",
        "order": len(logs) + 1,
        "title": "Final Quality Validation Completed",
        "description": f"Validation complete: {len(unresolved)} unresolved issue(s) reported.",
        "status": "Completed",
        "timestamp": _now_iso(),
    })
    timeline.append({
        "id": f"t_{len(logs)+2}",
        "order": len(logs) + 2,
        "title": "Cleaned Dataset Generated",
        "description": f"Verified clean file produced ({rows_final} rows, {cols_final} columns). Ready for export.",
        "status": "Completed",
        "timestamp": _now_iso(),
    })

    summary = {
        "total_operations_executed": len(logs),
        "applied_operations": applied_count,
        "checked_no_change_operations": checked_no_change_count,
        "flagged_operations": flagged_count,
        "skipped_operations": skipped_count,
        "failed_operations": failed_count,
        "rows_before": rows_init,
        "rows_after": rows_final,
        "rows_removed": rows_init - rows_final,
        "cols_before": cols_init,
        "cols_after": cols_final,
        "cols_removed": cols_init - cols_final,
        "duplicate_rows_removed": duplicate_rows_removed or (dups_init - dups_final),
        "missing_values_filled": missing_values_filled,
        "missing_values_remaining": nulls_final,
        "nulls_before": nulls_init,
        "nulls_after": nulls_final,
        "nulls_resolved": nulls_init - nulls_final,
        "duplicates_before": dups_init,
        "duplicates_after": dups_final,
        "duplicates_removed": dups_init - dups_final,
        "values_standardized": values_standardized,
        "type_conversions_performed": type_conversions_performed,
        "invalid_values_corrected_or_removed": invalid_corrected_or_removed,
        "outliers_flagged": outliers_flagged,
        "outliers_capped": outliers_capped,
        "outliers_removed": outliers_removed,
        "unresolved_issues": unresolved,
        "failed_or_skipped_operations": [l for l in logs if l.get("status") in ("Failed", "Skipped")],
        "execution_time_seconds": duration,
        "detailed_changes": all_detailed_changes,
        "quality_comparison": quality_comp,
        "timeline": timeline,
    }

    return final_cleaned_df, logs, summary


# ── CSV and Artifact Exporters ────────────────────────────────────────────────

def generate_transformation_log_csv(logs: list[dict[str, Any]]) -> str:
    """Generate structured transformation audit log CSV according to Section 1 & Section 7."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "order", "operation", "columns", "op_id", "name", "status",
        "issue_detected", "rows_inspected", "rows_affected", "cells_changed",
        "rows_removed", "missing_filled", "reason", "parameters", "timestamp", "error"
    ])

    for l in logs:
        order = l.get("order", 1)
        op_id = l.get("op_id", f"op_{order}")
        name = l.get("name", l.get("operation", "Cleaning Step"))
        op = l.get("operation", "cleaning")
        status = l.get("status", "Applied")
        cols = l.get("columns") or ([l.get("column")] if l.get("column") else [])
        cols_str = ";".join(str(c) for c in cols if c != ROW_ID_COL)
        issue = l.get("issue_detected", "")
        rows_insp = l.get("rows_inspected", 0)
        rows_aff = l.get("rows_affected", 0)
        cells_chg = l.get("cells_changed", 0)
        rows_rem = l.get("rows_removed", 0)
        miss_fill = l.get("missing_filled", 0)
        reason = l.get("reason", "")
        params_str = json.dumps(l.get("parameters", {}))
        ts = l.get("timestamp", _now_iso())
        err = l.get("error", "")

        writer.writerow([
            order, op, cols_str, op_id, name, status, issue,
            rows_insp, rows_aff, cells_chg, rows_rem, miss_fill,
            reason, params_str, ts, err
        ])

    return out.getvalue()


def generate_detailed_changes_csv(detailed_changes: list[dict[str, Any]]) -> str:
    """Generate cell-level and row-level detailed change table CSV according to Section 3."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row_id", "column", "original_value", "new_value", "operation", "status", "reason"])

    for ch in detailed_changes:
        writer.writerow([
            ch.get("row_id", "-"),
            ch.get("column", "-"),
            str(ch.get("original_value") if ch.get("original_value") is not None else ""),
            str(ch.get("new_value") if ch.get("new_value") is not None else ""),
            ch.get("operation", "-"),
            ch.get("status", "Applied"),
            ch.get("reason", ""),
        ])

    return out.getvalue()


def generate_quality_report_csv(quality_comparison: list[dict[str, Any]]) -> str:
    """Generate before-and-after data quality comparison CSV according to Section 5."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "column", "dtype_before", "dtype_after", "missing_before", "missing_after",
        "missing_diff", "invalid_before", "invalid_after", "outliers_before", "outliers_after",
        "changed_values", "unresolved_issues", "status"
    ])

    for q in quality_comparison:
        writer.writerow([
            q.get("column"),
            q.get("dtype_before"),
            q.get("dtype_after"),
            q.get("missing_before", 0),
            q.get("missing_after", 0),
            q.get("missing_diff", 0),
            q.get("invalid_before", 0),
            q.get("invalid_after", 0),
            q.get("outliers_before", 0),
            q.get("outliers_after", 0),
            q.get("changed_values", 0),
            q.get("unresolved_issues", 0),
            q.get("status", "unchanged"),
        ])

    return out.getvalue()


def generate_cleaning_report(
    dataset_id: str,
    original_filename: str,
    original_df: pd.DataFrame,
    cleaned_df: pd.DataFrame,
    logs: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Generate comprehensive JSON cleaning report according to Section 2, 5, 7, and 8."""
    prof_before = profile(original_df)
    prof_after = profile(cleaned_df)

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    detailed_changes = summary.get("detailed_changes", [])
    quality_comparison = summary.get("quality_comparison") or compute_quality_comparison(original_df, cleaned_df, detailed_changes)
    timeline = summary.get("timeline", [])

    report = {
        "dataset_id": dataset_id,
        "run_id": run_id,
        "original_filename": original_filename,
        "engine_version": ENGINE_VERSION,
        "generated_at": _now_iso(),
        "execution_time_seconds": summary.get("execution_time_seconds", 0.0),
        "summary": {
            **summary,
            "quality_score_before": prof_before["quality"]["score"],
            "quality_score_after": prof_after["quality"]["score"],
            "quality_gain": round(prof_after["quality"]["score"] - prof_before["quality"]["score"], 1),
        },
        "operations": logs,
        "operations_applied": logs,  # backward-compatibility
        "timeline": timeline,
        "quality_comparison": quality_comparison,
        "detailed_changes_sample": detailed_changes[:200],
        "total_detailed_changes": len(detailed_changes),
        "profile_before": prof_before["quality"],
        "profile_after": prof_after["quality"],
        "unresolved_issues": summary.get("unresolved_issues", []),
        "remaining_warnings": summary.get("unresolved_issues", []),
        "errors": [l["error"] for l in logs if l.get("error")],
    }
    return report
