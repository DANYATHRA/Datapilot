"""
High-performance Grid and Inline Cleaning Engine for DataPilot.
Provides:
  - Deep per-cell issue detection across 7 distinct categories:
    missing (amber), invalid_format (red), outlier (orange),
    typo (yellow), wrong_type (blue), duplicate (grey), personal_data (purple)
  - Semantic suggestions adhering to strict rules:
    * Identifiers (ID, roll no, order id), emails, phones, names, dates NEVER receive mean/median/mode
    * Plain 6-word explanation when statistical fill is prohibited ("Unique ID, so it can't be guessed")
    * Derived formula calculation & group medians (when group >= 5) for numbers/money
  - Single-cell and column-wide issue fixing
  - High-confidence "Fix all suggested" batch execution
  - Paged, virtualizable grid responses with issue annotations
  - Undo, redo, revert-to-original cell support
  - Clean workbook builder with Raw_Data (Tab 1) and Processed_Data (Tab 2)
"""
from __future__ import annotations

import datetime as dt
import io
import re
from typing import Any

import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

from .column_semantics import infer_dataset_semantics
from .missing_policy import (
    POLICY_MATRIX,
    detect_derived_formulas,
    find_best_group_column,
)

# ────────────────────────────────────────────────────────────────────────────
# Issue type definitions and styling metadata
# ────────────────────────────────────────────────────────────────────────────
ISSUE_CONFIG = {
    "missing": {
        "color": "amber",
        "badge_bg": "#FEF3C7",
        "badge_text": "#92400E",
        "border": "#F59E0B",
        "icon": "AlertCircle",
        "label": "Missing value",
    },
    "invalid_format": {
        "color": "red",
        "badge_bg": "#FEE2E2",
        "badge_text": "#991B1B",
        "border": "#EF4444",
        "icon": "AlertOctagon",
        "label": "Invalid format",
    },
    "outlier": {
        "color": "orange",
        "badge_bg": "#FFEDD5",
        "badge_text": "#9A3412",
        "border": "#F97316",
        "icon": "TrendingUp",
        "label": "Outlier",
    },
    "typo": {
        "color": "yellow",
        "badge_bg": "#FEF9C3",
        "badge_text": "#854D0E",
        "border": "#EAB308",
        "icon": "SpellCheck",
        "label": "Typo / Inconsistent",
    },
    "wrong_type": {
        "color": "blue",
        "badge_bg": "#DBEAFE",
        "badge_text": "#1E40AF",
        "border": "#3B82F6",
        "icon": "Type",
        "label": "Wrong type",
    },
    "duplicate": {
        "color": "grey",
        "badge_bg": "#F3F4F6",
        "badge_text": "#374151",
        "border": "#9CA3AF",
        "icon": "Copy",
        "label": "Duplicate row",
    },
    "personal_data": {
        "color": "purple",
        "badge_bg": "#F3E8FF",
        "badge_text": "#6B21A8",
        "border": "#A855F7",
        "icon": "ShieldAlert",
        "label": "Personal data",
    },
}

NULL_STRINGS = {"", "nan", "nan", "null", "none", "n/a", "na", "-", "nil", "undefined"}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_RE = re.compile(r"^(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}$")


def _is_missing(val: Any) -> bool:
    if val is None or pd.isna(val):
        return True
    s = str(val).strip().lower()
    return s in NULL_STRINGS


def _get_column_type_category(sem_type: str, dtype: Any) -> str:
    """Classify column into high-level type for grid icon and basic behaviors."""
    if sem_type in ("identifier",):
        return "id"
    if sem_type in ("money_amount", "currency"):
        return "money"
    if sem_type in ("quantity", "age", "rating_scale", "score/marks", "percentage", "other_numeric") or pd.api.types.is_numeric_dtype(dtype):
        return "number"
    if sem_type in ("date", "year") or pd.api.types.is_datetime64_any_dtype(dtype):
        return "date"
    if sem_type in ("email", "phone", "url", "postal_code"):
        return sem_type
    if sem_type in ("status/boolean_flag",) or pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    return "text"


def detect_issues_for_dataset(
    df: pd.DataFrame,
    semantics: dict[str, dict] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Detect all 7 issue types across the dataframe.
    Returns:
      - cells: dict of (row_idx, col_name) -> list of issue dicts
      - row_duplicates: set of duplicate row indices
      - counts_by_type: dict of issue_type -> total count
      - counts_by_column: dict of col_name -> total count
      - ordered_issues: list of {row, column, issue_type, label, message} ordered by row, col
      - column_stats: stats per column for grid presentation
    """
    if semantics is None:
        semantics = infer_dataset_semantics(df, overrides=overrides)

    cells: dict[tuple[int, str], list[dict]] = {}
    row_duplicates: set[int] = set()
    counts_by_type = {k: 0 for k in ISSUE_CONFIG}
    counts_by_column = {str(c): 0 for c in df.columns}
    ordered_issues = []

    # 1. Row Duplicates
    dup_mask = df.duplicated(keep="first")
    for r_idx in df[dup_mask].index:
        r_int = int(r_idx)
        row_duplicates.add(r_int)
        counts_by_type["duplicate"] += 1
        # Add duplicate marker to first column of the row
        first_col = str(df.columns[0])
        issue_obj = {
            "type": "duplicate",
            "label": "Duplicate row",
            "message": "Entire row is identical to an earlier row",
            "row": r_int,
            "column": first_col,
        }
        cells.setdefault((r_int, first_col), []).append(issue_obj)
        ordered_issues.append(issue_obj)

    # 2. Column-by-column issue scanning
    for col in df.columns:
        col_str = str(col)
        s = df[col]
        sem_info = semantics.get(col_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")
        type_cat = _get_column_type_category(sem_type, s.dtype)

        # Numeric outlier boundaries
        outlier_lower, outlier_upper = None, None
        is_numeric_col = pd.api.types.is_numeric_dtype(s) or sem_type in (
            "money_amount", "quantity", "percentage", "age", "rating_scale", "score/marks", "other_numeric"
        )
        if is_numeric_col and sem_type != "identifier":
            num_s = pd.to_numeric(s, errors="coerce").dropna()
            if len(num_s) >= 8:
                q25, q75 = num_s.quantile(0.25), num_s.quantile(0.75)
                iqr = q75 - q25
                if iqr > 0:
                    outlier_lower = q25 - 1.5 * iqr
                    outlier_upper = q75 + 1.5 * iqr

        # Frequency map for typo/inconsistent casing detection
        freq_map: dict[str, int] = {}
        canonical_map: dict[str, str] = {}
        if type_cat in ("text", "category") and sem_type not in ("identifier", "name", "email", "url"):
            valid_strings = [str(x).strip() for x in s.dropna() if not _is_missing(x)]
            for val in valid_strings:
                freq_map[val] = freq_map.get(val, 0) + 1
                norm = val.lower()
                # store the most frequent casing as canonical
                if norm not in canonical_map or freq_map[val] > freq_map.get(canonical_map[norm], 0):
                    canonical_map[norm] = val

        # Cell-level scanning
        for r_idx, val in s.items():
            r_int = int(r_idx)
            val_missing = _is_missing(val)

            # Issue 1: Missing
            if val_missing:
                issue_obj = {
                    "type": "missing",
                    "label": "Missing value",
                    "message": f"Missing value in {col_str}",
                    "row": r_int,
                    "column": col_str,
                }
                cells.setdefault((r_int, col_str), []).append(issue_obj)
                counts_by_type["missing"] += 1
                counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                ordered_issues.append(issue_obj)
                continue  # missing cells do not have format or outlier errors

            val_str = str(val).strip()

            # Issue 2: Invalid Format (Email, Phone, Date, URL)
            if sem_type == "email":
                if not EMAIL_RE.match(val_str):
                    issue_obj = {
                        "type": "invalid_format",
                        "label": "Invalid email",
                        "message": f"'{val_str}' is not a valid email address",
                        "row": r_int,
                        "column": col_str,
                    }
                    cells.setdefault((r_int, col_str), []).append(issue_obj)
                    counts_by_type["invalid_format"] += 1
                    counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                    ordered_issues.append(issue_obj)

            elif sem_type == "phone":
                digits = re.sub(r"\D", "", val_str)
                if len(digits) < 7 or len(digits) > 15:
                    issue_obj = {
                        "type": "invalid_format",
                        "label": "Invalid phone",
                        "message": f"'{val_str}' does not match standard phone numbers",
                        "row": r_int,
                        "column": col_str,
                    }
                    cells.setdefault((r_int, col_str), []).append(issue_obj)
                    counts_by_type["invalid_format"] += 1
                    counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                    ordered_issues.append(issue_obj)

            elif sem_type == "date":
                try:
                    pd.to_datetime(val_str)
                except Exception:
                    issue_obj = {
                        "type": "invalid_format",
                        "label": "Invalid date",
                        "message": f"'{val_str}' is not a recognized date format",
                        "row": r_int,
                        "column": col_str,
                    }
                    cells.setdefault((r_int, col_str), []).append(issue_obj)
                    counts_by_type["invalid_format"] += 1
                    counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                    ordered_issues.append(issue_obj)

            # Issue 3: Wrong Type (numeric column containing alpha/symbol text)
            if is_numeric_col:
                try:
                    # Clean currency symbols / commas for check
                    cleaned_num = re.sub(r"[^\d.-]", "", val_str)
                    num_val = float(cleaned_num) if cleaned_num not in ("", "-") else None
                    if num_val is None:
                        issue_obj = {
                            "type": "wrong_type",
                            "label": "Wrong type",
                            "message": f"Expected number, got text '{val_str}'",
                            "row": r_int,
                            "column": col_str,
                        }
                        cells.setdefault((r_int, col_str), []).append(issue_obj)
                        counts_by_type["wrong_type"] += 1
                        counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                        ordered_issues.append(issue_obj)
                    elif outlier_lower is not None and outlier_upper is not None:
                        # Issue 4: Outlier
                        if num_val < outlier_lower or num_val > outlier_upper:
                            issue_obj = {
                                "type": "outlier",
                                "label": "Outlier",
                                "message": f"{val_str} is outside expected range ({outlier_lower:,.1f} - {outlier_upper:,.1f})",
                                "row": r_int,
                                "column": col_str,
                                "bounds": [round(outlier_lower, 2), round(outlier_upper, 2)],
                            }
                            cells.setdefault((r_int, col_str), []).append(issue_obj)
                            counts_by_type["outlier"] += 1
                            counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                            ordered_issues.append(issue_obj)
                except Exception:
                    pass

            # Issue 5: Typo / Inconsistent casing / leading whitespace
            if col_str in df.columns and val_str:
                norm = val_str.lower()
                if norm in canonical_map:
                    canonical = canonical_map[norm]
                    if val_str != canonical:
                        issue_obj = {
                            "type": "typo",
                            "label": "Inconsistent text",
                            "message": f"Casing or typo: '{val_str}' -> '{canonical}'",
                            "row": r_int,
                            "column": col_str,
                            "canonical": canonical,
                        }
                        cells.setdefault((r_int, col_str), []).append(issue_obj)
                        counts_by_type["typo"] += 1
                        counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1
                        ordered_issues.append(issue_obj)

            # Issue 6: Personal Data (PII)
            if sem_type in ("email", "phone") or (sem_type == "name" and len(val_str) > 2):
                # We flag PII as personal_data notice for masking / compliance
                issue_obj = {
                    "type": "personal_data",
                    "label": "Personal data",
                    "message": f"Personal identifier ({sem_type})",
                    "row": r_int,
                    "column": col_str,
                }
                # To avoid cluttering every name cell, we tag email/phone cells
                if sem_type in ("email", "phone"):
                    cells.setdefault((r_int, col_str), []).append(issue_obj)
                    counts_by_type["personal_data"] += 1
                    counts_by_column[col_str] = counts_by_column.get(col_str, 0) + 1

    # Sort ordered issues by row, then col
    col_order = {c: i for i, c in enumerate(df.columns)}
    ordered_issues.sort(key=lambda x: (x["row"], col_order.get(x["column"], 999)))

    return {
        "cells": cells,
        "row_duplicates": row_duplicates,
        "counts_by_type": counts_by_type,
        "counts_by_column": counts_by_column,
        "ordered_issues": ordered_issues,
        "total_issues": sum(counts_by_type.values()),
    }


def get_suggestion_for_cell(
    df: pd.DataFrame,
    col: str,
    row: int,
    issue_type: str,
    semantics: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """
    Produce the semantic suggestion and options for a given cell issue.
    Strictly enforces:
      - Identifiers, emails, phones, names, dates NEVER mean/median/mode filled
      - 6-words-or-fewer reason why ("Unique ID, so it can't be guessed")
      - Group median where group >= 5 for numbers/money
      - Derived formulas detected across rows
    """
    if semantics is None:
        semantics = infer_dataset_semantics(df)

    sem_info = semantics.get(col, {})
    sem_type = sem_info.get("semantic_type", "other_text")
    s = df[col] if col in df.columns else pd.Series()
    row_val = df.at[row, col] if (col in df.columns and row in df.index) else None

    # Calculate column scope count: total cells in this column with this issue_type
    column_issue_count = 0
    if issue_type == "missing":
        missing_mask = s.isna() | s.astype(str).str.strip().str.lower().isin(NULL_STRINGS)
        column_issue_count = int(missing_mask.sum())
    elif issue_type == "invalid_format":
        if sem_type == "email":
            column_issue_count = int(s.dropna().apply(lambda v: not bool(EMAIL_RE.match(str(v).strip()))).sum())
        elif sem_type == "phone":
            column_issue_count = int(s.dropna().apply(lambda v: len(re.sub(r"\D", "", str(v))) not in range(7, 16)).sum())
        else:
            column_issue_count = 1
    elif issue_type == "outlier":
        num_s = pd.to_numeric(s, errors="coerce").dropna()
        if len(num_s) >= 8:
            q25, q75 = num_s.quantile(0.25), num_s.quantile(0.75)
            iqr = q75 - q25
            low, high = q25 - 1.5 * iqr, q75 + 1.5 * iqr
            column_issue_count = int(((num_s < low) | (num_s > high)).sum())
        else:
            column_issue_count = 1
    elif issue_type == "typo":
        column_issue_count = 1
    elif issue_type == "wrong_type":
        num_s = pd.to_numeric(s, errors="coerce")
        column_issue_count = int((s.notna() & num_s.isna()).sum())
    else:
        column_issue_count = 1

    # 1. IDENTIFIERS, EMAILS, PHONES, NAMES, DATES — Strict Non-Imputation Policy
    if sem_type in ("identifier", "email", "phone", "name", "date", "url", "postal_code"):
        reason_map = {
            "identifier": "Unique ID, so it can't be guessed",
            "email": "Email address, so it can't be guessed",
            "phone": "Phone number, so it can't be guessed",
            "name": "Personal name, cannot be inferred",
            "date": "Date value, cannot be averaged",
            "url": "Unique URL, cannot be guessed",
            "postal_code": "Postal code, cannot be averaged",
        }
        reason = reason_map.get(sem_type, "Unique value, cannot be guessed")

        # If invalid format, can suggest corrected format if possible
        if issue_type == "invalid_format":
            suggested_corr = ""
            corr_label = "Leave blank"
            strat = "leave_blank"
            if sem_type == "email":
                s_clean = str(row_val).strip().lower()
                if EMAIL_RE.match(s_clean):
                    suggested_corr = s_clean
                    corr_label = f"Use '{s_clean}'"
                    strat = "enter_value"
            elif sem_type == "date":
                try:
                    p = pd.to_datetime(row_val)
                    suggested_corr = p.strftime("%Y-%m-%d")
                    corr_label = f"Use '{suggested_corr}'"
                    strat = "enter_value"
                except Exception:
                    pass
            elif sem_type == "phone":
                digits = re.sub(r"\D", "", str(row_val))
                if 7 <= len(digits) <= 15:
                    suggested_corr = digits
                    corr_label = f"Use '{digits}'"
                    strat = "enter_value"

            opts = []
            if suggested_corr:
                opts.append({"label": corr_label, "strategy": "enter_value", "value": suggested_corr})
            opts.append({"label": "Leave blank", "strategy": "leave_blank", "value": ""})
            opts.append({"label": "Enter value", "strategy": "enter_value", "needs_input": True})

            return {
                "issue_type": issue_type,
                "column": col,
                "row": row,
                "line1": f"Invalid format in {col}",
                "line2": f"'{str(row_val)[:24]}' is invalid for {sem_type}",
                "suggested_value": suggested_corr,
                "suggested_label": corr_label if suggested_corr else "Leave blank",
                "primary_strategy": strat,
                "options": opts[:4],
                "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
                "is_restricted": True,
            }

        return {
            "issue_type": issue_type,
            "column": col,
            "row": row,
            "line1": f"Missing value in {col}" if issue_type == "missing" else f"Invalid {col}",
            "line2": reason,
            "suggested_value": "",
            "suggested_label": "Leave blank",
            "primary_strategy": "leave_blank",
            "options": [
                {"label": "Leave blank", "strategy": "leave_blank", "value": ""},
                {"label": "Enter value", "strategy": "enter_value", "needs_input": True},
                {"label": "Remove row", "strategy": "remove_row"},
            ],
            "scope_counts": {
                "cell": 1,
                "column": max(column_issue_count, 1),
            },
            "is_restricted": True,
        }

    # 2. DUPLICATE ROW ISSUE
    if issue_type == "duplicate":
        dup_count = int(df.duplicated(keep="first").sum())
        return {
            "issue_type": "duplicate",
            "column": col,
            "row": row,
            "line1": "Duplicate row",
            "line2": "Identical to an earlier row",
            "suggested_value": "",
            "suggested_label": "Remove duplicates (keep first)",
            "primary_strategy": "remove_duplicate_row",
            "options": [
                {"label": "Remove duplicates (keep first)", "strategy": "remove_duplicate_row"},
                {"label": "Keep", "strategy": "keep"},
            ],
            "scope_counts": {"cell": 1, "column": max(dup_count, 1)},
            "is_restricted": False,
        }

    # 3. PERSONAL DATA (PII) ISSUE
    if issue_type == "personal_data":
        return {
            "issue_type": "personal_data",
            "column": col,
            "row": row,
            "line1": f"Personal data in {col}",
            "line2": f"Identified as personal {sem_type}",
            "suggested_value": "[MASKED]",
            "suggested_label": "Mask",
            "primary_strategy": "mask_pii",
            "options": [
                {"label": "Mask", "strategy": "mask_pii", "value": "[MASKED]"},
                {"label": "Keep", "strategy": "keep"},
            ],
            "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
            "is_restricted": False,
        }

    # 4. OUTLIER ISSUE
    if issue_type == "outlier":
        num_s = pd.to_numeric(s, errors="coerce").dropna()
        capped_val = 0
        low_b, high_b = 0, 0
        if len(num_s) >= 8:
            q25, q75 = num_s.quantile(0.25), num_s.quantile(0.75)
            iqr = q75 - q25
            low_b, high_b = q25 - 1.5 * iqr, q75 + 1.5 * iqr
            cur_num = pd.to_numeric(row_val, errors="coerce")
            if pd.notna(cur_num):
                capped_val = high_b if cur_num > high_b else low_b
            else:
                capped_val = high_b
        if sem_type in ("quantity", "age"):
            capped_val = int(round(capped_val))
        else:
            capped_val = round(float(capped_val), 2)

        return {
            "issue_type": "outlier",
            "column": col,
            "row": row,
            "line1": f"Outlier in {col}",
            "line2": f"Outside normal range ({low_b:,.0f} - {high_b:,.0f})",
            "suggested_value": capped_val,
            "suggested_label": f"Limit to {capped_val}",
            "primary_strategy": "limit_range",
            "options": [
                {"label": "Limit to normal range", "strategy": "limit_range", "value": capped_val},
                {"label": "Keep as is", "strategy": "keep"},
                {"label": "Enter value", "strategy": "enter_value", "needs_input": True},
            ],
            "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
            "is_restricted": False,
        }

    # 2. DERIVED FORMULAS (e.g. Total = Units * Unit_Price)
    formulas = detect_derived_formulas(df)
    formula_match = next((f for f in formulas if f["target"] == col), None)
    if formula_match and row in df.index:
        try:
            row_dict = df.loc[row].to_dict()
            sub_df = pd.DataFrame([row_dict])
            calc_val = formula_match["fn"](sub_df).iloc[0]
            if pd.notna(calc_val) and not np.isinf(calc_val):
                formatted_calc = round(float(calc_val), 2)
                expr = formula_match["expression"]
                return {
                    "issue_type": issue_type,
                    "column": col,
                    "row": row,
                    "line1": f"Missing value in {col}",
                    "line2": f"{formatted_calc} · computed from {expr}",
                    "suggested_value": formatted_calc,
                    "suggested_label": f"Apply formula ({formatted_calc})",
                    "primary_strategy": "formula",
                    "options": [
                        {"label": f"Formula ({formatted_calc})", "strategy": "formula", "value": formatted_calc},
                        {"label": "Median", "strategy": "median"},
                        {"label": "Enter value", "strategy": "enter_value", "needs_input": True},
                        {"label": "Leave blank", "strategy": "leave_blank", "value": ""},
                    ],
                    "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
                    "is_restricted": False,
                }
        except Exception:
            pass

    # 3. NUMBERS / MONEY (Group Median, Global Median, Mean)
    is_num = pd.api.types.is_numeric_dtype(s) or sem_type in ("money_amount", "quantity", "percentage", "other_numeric", "age")
    if is_num:
        num_clean = pd.to_numeric(s, errors="coerce").dropna()
        global_median = round(float(num_clean.median()), 2) if not num_clean.empty else 0
        global_mean = round(float(num_clean.mean()), 2) if not num_clean.empty else 0
        if sem_type in ("quantity", "age"):
            global_median = int(round(global_median))
            global_mean = int(round(global_mean))

        # Check for group median
        group_col = find_best_group_column(df, col, semantics)
        group_median_val = None
        group_name = None
        if group_col and row in df.index:
            group_val = df.at[row, group_col]
            if pd.notna(group_val) and not _is_missing(group_val):
                group_mask = df[group_col] == group_val
                group_nums = pd.to_numeric(df.loc[group_mask, col], errors="coerce").dropna()
                if len(group_nums) >= 3:
                    group_median_val = round(float(group_nums.median()), 2)
                    if sem_type in ("quantity", "age"):
                        group_median_val = int(round(group_median_val))
                    group_name = str(group_val)

        suggested = group_median_val if group_median_val is not None else global_median
        line2_reason = (
            f"{suggested} · typical for {group_name}"
            if group_name
            else f"{suggested} · column median"
        )

        options = [
            {"label": "Median", "strategy": "median", "value": global_median},
            {"label": "Mean", "strategy": "mean", "value": global_mean},
        ]
        if group_median_val is not None:
            options.insert(0, {"label": f"Median of {group_name}", "strategy": "group_median", "value": group_median_val})
        options.append({"label": "Enter value", "strategy": "enter_value", "needs_input": True})
        options.append({"label": "Leave blank", "strategy": "leave_blank", "value": ""})

        return {
            "issue_type": issue_type,
            "column": col,
            "row": row,
            "line1": f"Missing value in {col}" if issue_type == "missing" else f"{issue_type.replace('_', ' ').capitalize()} in {col}",
            "line2": line2_reason,
            "suggested_value": suggested,
            "suggested_label": f"Apply {suggested}",
            "primary_strategy": "group_median" if group_median_val is not None else "median",
            "options": options[:4],
            "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
            "is_restricted": False,
        }

    # 4. CATEGORIES / STATUS / TEXT
    clean_text = s[~s.isna() & ~s.astype(str).str.strip().str.lower().isin(NULL_STRINGS)]
    mode_val = str(clean_text.mode()[0]) if not clean_text.empty and not clean_text.mode().empty else "Unknown"

    if issue_type == "typo":
        # Check standard spelling
        norm = str(row_val).strip().lower() if row_val is not None else ""
        canonical = mode_val
        for v in clean_text.unique():
            if str(v).strip().lower() == norm:
                canonical = str(v).strip()
                break
        return {
            "issue_type": "typo",
            "column": col,
            "row": row,
            "line1": f"Inconsistent text in {col}",
            "line2": f"Standardize to '{canonical}'",
            "suggested_value": canonical,
            "suggested_label": f"Use '{canonical}'",
            "primary_strategy": "standardize",
            "options": [
                {"label": "Use standard spelling", "strategy": "standardize", "value": canonical},
                {"label": "Keep as is", "strategy": "keep"},
            ],
            "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
            "is_restricted": False,
        }

    return {
        "issue_type": issue_type,
        "column": col,
        "row": row,
        "line1": f"Missing value in {col}",
        "line2": f"'{mode_val}' · most common in this column",
        "suggested_value": mode_val,
        "suggested_label": f"Apply '{mode_val}'",
        "primary_strategy": "mode",
        "options": [
            {"label": "Most common", "strategy": "mode", "value": mode_val},
            {"label": '"Unknown"', "strategy": "unknown", "value": "Unknown"},
            {"label": "Enter value", "strategy": "enter_value", "needs_input": True},
            {"label": "Leave blank", "strategy": "leave_blank", "value": ""},
        ],
        "scope_counts": {"cell": 1, "column": max(column_issue_count, 1)},
        "is_restricted": False,
    }


def apply_cell_or_column_fix(
    df: pd.DataFrame,
    issue_type: str,
    column: str,
    row: int | None,
    strategy: str,
    value: Any = None,
    scope: str = "cell",
    semantics: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, int, list[dict]]:
    """
    Apply fix for an issue either to a single cell or across all matching cells in that column.
    Returns:
      (new_df, affected_count, list_of_change_log_entries)
    """
    df = df.copy()
    changes = []
    sem_info = semantics.get(column, {}) if semantics else {}
    sem_type = sem_info.get("semantic_type", "other_text")

    # Safety check: Prevent mean/median/mode on forbidden semantic types
    if sem_type in ("identifier", "email", "phone", "name", "date", "url", "postal_code") and strategy in ("mean", "median", "group_median", "mode"):
        raise ValueError(f"Statistical imputation ({strategy}) is strictly prohibited for {sem_type} column '{column}'.")

    # Determine target rows
    if scope == "cell":
        if row is None or row not in df.index:
            raise ValueError(f"Invalid row {row}")
        target_rows = [row]
    else:
        # Column-wide scope: find rows with this issue
        s = df[column]
        if issue_type == "missing":
            mask = s.isna() | s.astype(str).str.strip().str.lower().isin(NULL_STRINGS)
            target_rows = list(df[mask].index)
        elif issue_type == "typo":
            # standardise casing across column
            target_rows = list(df.index)
        elif issue_type == "outlier":
            num_s = pd.to_numeric(s, errors="coerce")
            q25, q75 = num_s.quantile(0.25), num_s.quantile(0.75)
            iqr = q75 - q25
            low, high = q25 - 1.5 * iqr, q75 + 1.5 * iqr
            mask = (num_s < low) | (num_s > high)
            target_rows = list(df[mask].index)
        else:
            target_rows = [row] if row is not None else list(df.index)

    affected = 0
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    if strategy in ("remove_row", "remove_duplicate_row"):
        if strategy == "remove_duplicate_row" and scope != "cell":
            dup_mask = df.duplicated(keep="first")
            rows_to_drop = list(df[dup_mask].index)
        else:
            rows_to_drop = [r for r in target_rows if r in df.index]
        affected = len(rows_to_drop)
        df = df.drop(index=rows_to_drop).reset_index(drop=True)
        changes.append({
            "cell": f"{column}:rows",
            "row": row,
            "column": column,
            "old_val": "row",
            "new_val": "deleted",
            "source": f"fix_{strategy}_{scope}",
            "time": now_iso,
        })
        return df, affected, changes

    if strategy == "keep":
        return df, 0, []

    if strategy == "limit_range":
        num_s = pd.to_numeric(s, errors="coerce").dropna()
        if len(num_s) >= 8:
            q25, q75 = num_s.quantile(0.25), num_s.quantile(0.75)
            iqr = q75 - q25
            low_b, high_b = q25 - 1.5 * iqr, q75 + 1.5 * iqr
            for r in target_rows:
                if r not in df.index:
                    continue
                cur_v = pd.to_numeric(df.at[r, column], errors="coerce")
                if pd.notna(cur_v):
                    capped = high_b if cur_v > high_b else (low_b if cur_v < low_b else cur_v)
                    if sem_type in ("quantity", "age"):
                        capped = int(round(capped))
                    else:
                        capped = round(float(capped), 2)
                    old_val = df.at[r, column]
                    df.at[r, column] = capped
                    affected += 1
                    changes.append({
                        "cell": f"{column}[{r}]",
                        "row": r,
                        "column": column,
                        "old_val": str(old_val),
                        "new_val": str(capped),
                        "source": f"fix_limit_range_{scope}",
                        "time": now_iso,
                    })
            return df, affected, changes

    if strategy == "mask_pii":
        for r in target_rows:
            if r not in df.index:
                continue
            old_val = df.at[r, column]
            old_str = str(old_val)
            if sem_type == "email" and "@" in old_str:
                prefix, domain = old_str.split("@", 1)
                masked = f"{prefix[:1]}***@{domain}"
            elif sem_type == "phone":
                masked = f"***-***-{old_str[-4:]}" if len(old_str) >= 4 else "***-****"
            else:
                masked = "[REDACTED]"
            df.at[r, column] = masked
            affected += 1
            changes.append({
                "cell": f"{column}[{r}]",
                "row": r,
                "column": column,
                "old_val": old_str,
                "new_val": masked,
                "source": f"fix_mask_pii_{scope}",
                "time": now_iso,
            })
        return df, affected, changes

    # Resolve fill value
    fill_val = value
    s = df[column]
    if strategy in ("enter_value", "custom_value"):
        fill_val = value
    elif strategy == "median":
        num_s = pd.to_numeric(s, errors="coerce").dropna()
        fill_val = round(float(num_s.median()), 2) if not num_s.empty else 0
        if sem_type in ("quantity", "age"):
            fill_val = int(round(fill_val))
    elif strategy == "mean":
        num_s = pd.to_numeric(s, errors="coerce").dropna()
        fill_val = round(float(num_s.mean()), 2) if not num_s.empty else 0
        if sem_type in ("quantity", "age"):
            fill_val = int(round(fill_val))
    elif strategy == "mode":
        clean = s[~s.isna() & ~s.astype(str).str.strip().str.lower().isin(NULL_STRINGS)]
        fill_val = clean.mode()[0] if not clean.empty and not clean.mode().empty else "Unknown"
    elif strategy == "unknown":
        fill_val = "Unknown"
    elif strategy == "leave_blank":
        fill_val = ""
    elif strategy == "group_median":
        if fill_val is None:
            group_col = find_best_group_column(df, column, semantics or {})
            if group_col and row is not None and row in df.index:
                g_val = df.at[row, group_col]
                sub = pd.to_numeric(df.loc[df[group_col] == g_val, column], errors="coerce").dropna()
                fill_val = round(float(sub.median()), 2) if not sub.empty else 0
            else:
                num_s = pd.to_numeric(s, errors="coerce").dropna()
                fill_val = round(float(num_s.median()), 2) if not num_s.empty else 0

    # Apply changes
    for r in target_rows:
        if r not in df.index:
            continue
        old_val = df.at[r, column]
        df.at[r, column] = fill_val
        affected += 1
        changes.append({
            "cell": f"{column}[{r}]",
            "row": r,
            "column": column,
            "old_val": None if pd.isna(old_val) else str(old_val),
            "new_val": str(fill_val),
            "source": f"fix_{strategy}_{scope}",
            "time": now_iso,
        })

    return df, affected, changes


def validate_cell_value(val_str: str, col: str, sem_type: str, dtype: Any) -> tuple[bool, Any, str]:
    """
    Validate a user's manual cell input against column type and semantic meaning.
    Returns: (is_valid, parsed_value, error_message)
    """
    val_clean = str(val_str).strip()

    # Empty string is valid (clear cell / blank)
    if val_clean == "":
        return True, "", ""

    # Numeric validations
    is_numeric = sem_type in ("money_amount", "quantity", "percentage", "age", "rating_scale", "score/marks", "other_numeric") or pd.api.types.is_numeric_dtype(dtype)
    if is_numeric and sem_type != "identifier":
        try:
            # allow standard currency/comma signs
            cleaned = re.sub(r"[^\d.-]", "", val_clean)
            num = float(cleaned)
            if sem_type in ("quantity", "age") or num.is_integer():
                return True, int(round(num)), ""
            return True, round(num, 4), ""
        except Exception:
            return False, None, f"'{val_str}' is not a valid number"

    # Date validation
    if sem_type in ("date",) or pd.api.types.is_datetime64_any_dtype(dtype):
        try:
            parsed = pd.to_datetime(val_clean)
            return True, parsed.strftime("%Y-%m-%d"), ""
        except Exception:
            return False, None, f"'{val_str}' is not a valid date (use YYYY-MM-DD)"

    # Email validation
    if sem_type == "email":
        if not EMAIL_RE.match(val_clean):
            return False, None, f"'{val_str}' is not a valid email address (e.g. user@domain.com)"
        return True, val_clean.lower(), ""

    # Phone validation
    if sem_type == "phone":
        digits = re.sub(r"\D", "", val_clean)
        if len(digits) < 7 or len(digits) > 15:
            return False, None, f"'{val_str}' must contain between 7 and 15 digits"
        return True, val_clean, ""

    return True, val_clean, ""


def fix_all_high_confidence_suggested(
    df: pd.DataFrame,
    semantics: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, dict[str, int], list[dict], dict[str, Any]]:
    """
    Toolbar action 'Fix all suggested' (Completeness Contract A1 & A2):
      - Runs repeated passes until a pass changes nothing (max 5 passes)
      - Covers all detectors & fixers (structure, missing tokens, text, numbers, dates, categories, IDs, rows)
      - Preserves strict semantic rules (IDs/emails/phones/names/dates left blank for human decision)
      - Runs post-cleaning Clean Check asserting 0 auto-fixable issues remain
      - Returns (new_df, counts_per_issue_type, changes_log, clean_check_result)
    """
    from .complete_cleaner import run_multi_pass_auto_clean, run_clean_check

    if semantics is None:
        semantics = infer_dataset_semantics(df)

    new_df, all_changes, removed_rows, passes_count = run_multi_pass_auto_clean(
        df,
        semantics=semantics,
        max_passes=5,
    )

    resolved_counts = {k: 0 for k in ISSUE_CONFIG}
    for ch in all_changes:
        rule = ch.get("rule", "")
        if "missing" in rule or "median" in rule or "formula" in rule:
            resolved_counts["missing"] += 1
        elif "number" in rule or "date" in rule:
            resolved_counts["wrong_type"] += 1
        elif "typo" in rule or "text" in rule or "boolean" in rule:
            resolved_counts["typo"] += 1
        elif "dup" in rule:
            resolved_counts["duplicate"] += 1
        else:
            resolved_counts["invalid_format"] += 1

    clean_check = run_clean_check(new_df, semantics=semantics)

    return new_df, resolved_counts, all_changes, clean_check


def build_raw_and_processed_workbook(
    raw_df: pd.DataFrame | None = None,
    processed_df: pd.DataFrame | None = None,
    edit_log: list[dict] | None = None,
    include_change_log: bool = True,
    highlight_changes: bool = False,
    sheet_name: str = "Data",
    needs_review_items: list[dict] | None = None,
    multi_sheets: dict[str, tuple[pd.DataFrame, pd.DataFrame]] | None = None,
) -> bytes:
    """
    Export Excel workbook containing:
      Tab 1: Raw_Data (exactly as uploaded, values unmodified)
      Tab 2: Processed_Data (cleaned, typed cells: real numbers, dates with date format,
             bold frozen headers, autofilter, sensible widths)
      Optional Tab 3: Change_Log (when include_change_log=True)
      Optional Tab 4: Needs_Review (when unresolved flagged items exist)
      Multi-sheet uploads produce Raw_<sheet> then Processed_<sheet> pairs.
    """
    wb = openpyxl.Workbook()

    # Style definitions
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    fill_header = PatternFill(start_color="0B7A75", end_color="0B7A75", fill_type="solid")
    font_body = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        top=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )
    changed_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")

    def _write_sheet(ws, dataframe: pd.DataFrame, is_processed: bool = False):
        if dataframe is None or dataframe.empty:
            ws.cell(row=1, column=1, value="")
            return

        # Freeze top row
        ws.freeze_panes = "A2"

        # Headers
        headers = list(dataframe.columns)
        for col_i, col_name in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_i, value=str(col_name))
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Enable AutoFilter
        last_col_letter = get_column_letter(max(len(headers), 1))
        ws.auto_filter.ref = f"A1:{last_col_letter}{len(dataframe) + 1}"

        # Write Data
        for row_i, row_data in enumerate(dataframe.itertuples(index=False), start=2):
            for col_i, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_i, column=col_i)
                cell.font = font_body
                cell.border = thin_border

                if pd.isna(val) or val is None:
                    cell.value = ""
                elif isinstance(val, (int, np.integer)):
                    cell.value = int(val)
                    cell.number_format = "#,##0"
                elif isinstance(val, (float, np.floating)):
                    if np.isnan(val) or np.isinf(val):
                        cell.value = ""
                    else:
                        cell.value = float(val)
                        cell.number_format = "#,##0.00" if abs(val) >= 1 else "0.00"
                elif isinstance(val, (dt.date, dt.datetime)):
                    cell.value = val
                    cell.number_format = "YYYY-MM-DD"
                else:
                    s_val = str(val).strip()
                    if is_processed:
                        try:
                            if "." in s_val:
                                cell.value = float(s_val)
                                cell.number_format = "#,##0.00"
                            else:
                                cell.value = int(s_val)
                                cell.number_format = "#,##0"
                        except ValueError:
                            cell.value = s_val
                    else:
                        cell.value = s_val

        # Sensible column widths
        for col_i, col_name in enumerate(headers, start=1):
            col_letter = get_column_letter(col_i)
            max_len = len(str(col_name))
            sample = dataframe.iloc[:100, col_i - 1].dropna().astype(str)
            if not sample.empty:
                max_len = max(max_len, sample.str.len().max())
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 45)

    if multi_sheets:
        first = True
        for s_title, (r_df, p_df) in multi_sheets.items():
            raw_title = f"Raw_{s_title}"
            clean_title = f"Processed_{s_title}"
            if first:
                ws_r = wb.active
                ws_r.title = raw_title
                first = False
            else:
                ws_r = wb.create_sheet(raw_title)
            _write_sheet(ws_r, r_df, is_processed=False)

            ws_p = wb.create_sheet(clean_title)
            _write_sheet(ws_p, p_df, is_processed=True)
    else:
        # Single sheet mode
        raw_title = "Raw_Data" if sheet_name in ("Data", "Sheet1") else f"Raw_{sheet_name}"
        clean_title = "Processed_Data" if sheet_name in ("Data", "Sheet1") else f"Processed_{sheet_name}"

        ws_raw = wb.active
        ws_raw.title = raw_title
        _write_sheet(ws_raw, raw_df if raw_df is not None else pd.DataFrame(), is_processed=False)

        ws_proc = wb.create_sheet(clean_title)
        _write_sheet(ws_proc, processed_df if processed_df is not None else pd.DataFrame(), is_processed=True)

    # Highlight changed cells if requested
    if highlight_changes and edit_log:
        cols_list = list(processed_df.columns)
        for edit in edit_log:
            r = edit.get("row")
            c = edit.get("column")
            if r is not None and c in cols_list:
                try:
                    xl_row = int(r) + 2
                    xl_col = cols_list.index(c) + 1
                    if xl_row <= len(processed_df) + 1:
                        ws_proc.cell(row=xl_row, column=xl_col).fill = changed_fill
                except Exception:
                    pass

    # ── Optional TAB 3: Change_Log ──
    if include_change_log and edit_log:
        ws_log = wb.create_sheet("Change_Log")
        ws_log.freeze_panes = "A2"
        log_headers = ["Timestamp", "Cell", "Column", "Row", "Old Value", "New Value", "Source"]
        for col_i, h in enumerate(log_headers, start=1):
            c = ws_log.cell(row=1, column=col_i, value=h)
            c.font = font_header
            c.fill = fill_header

        for row_i, entry in enumerate(edit_log, start=2):
            ws_log.cell(row=row_i, column=1, value=str(entry.get("time", "")))
            ws_log.cell(row=row_i, column=2, value=str(entry.get("cell", "")))
            ws_log.cell(row=row_i, column=3, value=str(entry.get("column", "")))
            ws_log.cell(row=row_i, column=4, value=entry.get("row", ""))
            ws_log.cell(row=row_i, column=5, value=str(entry.get("old_val", "")))
            ws_log.cell(row=row_i, column=6, value=str(entry.get("new_val", "")))
            ws_log.cell(row=row_i, column=7, value=str(entry.get("source", "")))

        for i in range(1, 8):
            ws_log.column_dimensions[get_column_letter(i)].width = 20

    # ── Optional TAB 4: Needs_Review ──
    if needs_review_items:
        ws_rev = wb.create_sheet("Needs_Review")
        ws_rev.freeze_panes = "A2"
        rev_headers = ["Row", "Column", "Current Value", "Issue", "Reason"]
        for col_i, h in enumerate(rev_headers, start=1):
            c = ws_rev.cell(row=1, column=col_i, value=h)
            c.font = font_header
            c.fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")

        for row_i, item in enumerate(needs_review_items, start=2):
            ws_rev.cell(row=row_i, column=1, value=item.get("row", ""))
            ws_rev.cell(row=row_i, column=2, value=str(item.get("column", "")))
            ws_rev.cell(row=row_i, column=3, value=str(item.get("value", "")))
            ws_rev.cell(row=row_i, column=4, value=str(item.get("issue", "")))
            ws_rev.cell(row=row_i, column=5, value=str(item.get("reason", "")))

        for i in range(1, 6):
            ws_rev.column_dimensions[get_column_letter(i)].width = 22

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
