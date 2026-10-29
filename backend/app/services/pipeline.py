"""
Auto-clean pipeline — 10 fixed stages executed in order with Column-Aware Semantic Cleaning.

Colour legend is the SINGLE SOURCE OF TRUTH, used by backend (export) and
exposed at GET /pipeline/legend for the frontend.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import io
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rapidfuzz import fuzz

from ..config import settings
from .column_semantics import infer_column_semantic_type, infer_dataset_semantics
from .missing_policy import (
    POLICY_MATRIX,
    detect_derived_formulas,
    find_best_group_column,
    get_preview_line,
)
from .profiling import (
    CURRENCY_CHARS,
    PII_PATTERNS,
    date_like_ratio,
    detect_pii,
    numeric_like_ratio,
    profile,
)
from .util import text_cols

# ────────────────────────────────────────────────────────────────────────────
# COLOUR LEGEND — single source of truth
# ────────────────────────────────────────────────────────────────────────────
STAGE_COLOURS: dict[str, dict] = {
    "structure":        {"hex": "808080", "name": "Grey",   "label": "Structure fixed",        "marker": "[STR]"},
    "column_names":     {"hex": "808080", "name": "Grey",   "label": "Column renamed",         "marker": "[COL]"},
    "text_hygiene":     {"hex": "FFFF00", "name": "Yellow", "label": "Text cleaned",           "marker": "[TXT]"},
    "data_types":       {"hex": "4472C4", "name": "Blue",   "label": "Type converted",         "marker": "[TYP]"},
    "value_standardisation": {"hex": "00B0F0", "name": "Teal", "label": "Category standardised", "marker": "[STD]"},
    "missing_values":   {"hex": "00B050", "name": "Green",  "label": "Missing value filled",   "marker": "[MIS]"},
    "duplicates":       {"hex": "FF0000", "name": "Red",    "label": "Row removed (duplicate)","marker": "[DUP]"},
    "outliers":         {"hex": "FFC000", "name": "Orange", "label": "Outlier clipped",        "marker": "[OUT]"},
    "pii":              {"hex": "7030A0", "name": "Purple", "label": "PII masked",             "marker": "[PII]"},
    "validation":       {"hex": "FFFFFF", "name": "White",  "label": "Validation (no change)", "marker": "[VAL]"},
    "review":           {"hex": "FFB6C1", "name": "Pink",   "label": "Flagged for review",     "marker": "[?]"},
    "removed_row":      {"hex": "FF0000", "name": "Red",    "label": "Row removed",            "marker": "[DEL]"},
}

STAGE_ORDER = [
    "structure",
    "column_names",
    "text_hygiene",
    "data_types",
    "value_standardisation",
    "missing_values",
    "duplicates",
    "outliers",
    "pii",
    "validation",
]


def get_legend() -> list[dict]:
    """Return the colour legend for the API / frontend."""
    out = []
    for key in STAGE_ORDER + ["review", "removed_row"]:
        c = STAGE_COLOURS[key]
        out.append({
            "stage": key,
            "colour_hex": f"#{c['hex']}",
            "colour_name": c["name"],
            "label": c["label"],
            "marker": c["marker"],
        })
    return out


# ────────────────────────────────────────────────────────────────────────────
# CHANGE RECORD helper
# ────────────────────────────────────────────────────────────────────────────
def _rec(stage: str, sheet: str, row: int | str, column: str,
         old_value: Any, new_value: Any, reason: str) -> dict:
    return {
        "stage": stage,
        "sheet": sheet,
        "row": row,
        "column": column,
        "old_value": _safe(old_value),
        "new_value": _safe(new_value),
        "reason": reason,
    }


def _safe(v) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (pd.Timestamp, np.datetime64, _dt.datetime, _dt.date)):
        return str(v)
    return str(v)


# ────────────────────────────────────────────────────────────────────────────
# STAGE 1 — Structure
# ────────────────────────────────────────────────────────────────────────────
def _detect_header_row(df: pd.DataFrame) -> int | None:
    if len(df) < 3:
        return None
    for i in range(min(5, len(df) - 1)):
        row = df.iloc[i]
        non_null = row.dropna()
        if len(non_null) == 0:
            continue
        if all(isinstance(v, str) for v in non_null) and non_null.nunique() == len(non_null):
            if i > 0 and df.iloc[:i].isna().all(axis=1).all():
                return i
    return None


def _is_junk_row(row: pd.Series) -> bool:
    vals = row.dropna().astype(str).str.lower()
    if vals.empty:
        return False
    first = vals.iloc[0] if len(vals) else ""
    junk_keywords = ("total", "subtotal", "sub-total", "grand total", "sum", "count")
    if any(first.startswith(kw) for kw in junk_keywords):
        return True
    return False


def stage_structure(df: pd.DataFrame, sheet: str, **kwargs) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()

    # 1a Drop fully-empty rows
    empty_mask = df.isna().all(axis=1)
    empty_idxs = df.index[empty_mask].tolist()
    for idx in empty_idxs:
        changes.append(_rec("structure", sheet, int(idx), "*",
                            "(empty row)", "(removed)", "Fully empty row removed"))
    df = df.loc[~empty_mask].reset_index(drop=True)

    # 1b Drop fully-empty columns
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    for c in empty_cols:
        changes.append(_rec("structure", sheet, "*", str(c),
                            "(empty column)", "(removed)", "Fully empty column removed"))
    df = df.drop(columns=empty_cols)

    # 1c Detect and promote header row
    hdr = _detect_header_row(df)
    if hdr is not None and hdr > 0:
        new_cols = df.iloc[hdr].astype(str).tolist()
        for i, (old, new) in enumerate(zip(df.columns, new_cols)):
            if str(old) != new:
                changes.append(_rec("structure", sheet, "*", str(old),
                                    str(old), new, f"Header row detected at row {hdr}"))
        df.columns = new_cols
        df = df.iloc[hdr + 1:].reset_index(drop=True)

    # 1d Drop junk/total rows
    junk_mask = df.apply(_is_junk_row, axis=1)
    junk_idxs = df.index[junk_mask].tolist()
    for idx in junk_idxs:
        row_vals = df.loc[idx].to_dict()
        changes.append(_rec("structure", sheet, int(idx), "*",
                            str(row_vals), "(removed)", "Junk/total row removed"))
    df = df.loc[~junk_mask].reset_index(drop=True)

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 2 — Column names
# ────────────────────────────────────────────────────────────────────────────
def _snake_case(name: str) -> str:
    s = str(name).strip()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_") or "column"


def stage_column_names(df: pd.DataFrame, sheet: str, **kwargs) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    new_cols = []
    seen: dict[str, int] = {}
    for old in df.columns:
        sc = _snake_case(old)
        n = seen.get(sc, 0)
        seen[sc] = n + 1
        final = sc if n == 0 else f"{sc}_{n}"
        new_cols.append(final)
        if str(old) != final:
            changes.append(_rec("column_names", sheet, "*", str(old),
                                str(old), final, "Column name standardised to snake_case"))
    df.columns = new_cols
    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 3 — Text hygiene (Column-aware casing and sanitization)
# ────────────────────────────────────────────────────────────────────────────
_NON_PRINT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def stage_text_hygiene(df: pd.DataFrame, sheet: str, semantics: dict[str, dict] | None = None, **kwargs) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    semantics = semantics or infer_dataset_semantics(df)

    for c in text_cols(df):
        sem_type = semantics.get(c, {}).get("semantic_type", "other_text")
        s = df[c]
        for idx in s.index:
            v = s.at[idx]
            if pd.isna(v) or not isinstance(v, str):
                continue
            new = v.strip()
            new = re.sub(r"\s{2,}", " ", new)  # collapse multiple spaces
            new = _NON_PRINT.sub("", new)       # strip non-printing chars

            # Case rules per requirement:
            # names Title Case, emails lowercase, codes/IDs uppercase, free text untouched
            if sem_type == "name":
                new = new.title()
            elif sem_type == "email":
                new = new.lower()
            elif sem_type in ("identifier", "url"):
                new = new.upper() if sem_type == "identifier" else new
            elif sem_type in ("address/free_text", "other_text"):
                # Free text untouched (preserve original case)
                pass
            elif sem_type == "category":
                new = new.title()
            else:
                new = new.strip()

            if new != v:
                changes.append(_rec("text_hygiene", sheet, int(idx), c, v, new,
                                    f"Text sanitized / cased for {sem_type}"))
                df.at[idx, c] = new
    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 4 — Data types (Text preserved for IDs, phone, postal code, Aadhaar, PAN)
# ────────────────────────────────────────────────────────────────────────────
_YES_NO = {"yes": True, "no": False, "y": True, "n": False, "true": True, "false": False,
           "1": True, "0": False}


def stage_data_types(df: pd.DataFrame, sheet: str, semantics: dict[str, dict] | None = None, **kwargs) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    semantics = semantics or infer_dataset_semantics(df)

    for c in df.columns:
        sem_type = semantics.get(c, {}).get("semantic_type", "")
        s = df[c]
        non_null = s.dropna()
        if non_null.empty:
            continue

        # RULE: identifiers, phone, postal code, Aadhaar and PAN stay TEXT
        # (keep leading zeros, no thousands separators, never 9.78e+09 or ".0")
        if sem_type in ("identifier", "phone", "postal_code", "url") or "aadhaar" in sem_type or "pan" in sem_type:
            def _clean_text_id(v):
                if pd.isna(v):
                    return None
                s_val = str(v).strip()
                if s_val.endswith(".0"):
                    s_val = s_val[:-2]
                return s_val

            new_col = s.map(_clean_text_id)
            for idx in non_null.index:
                old_v = s.at[idx]
                clean_v = new_col.at[idx]
                if str(old_v) != str(clean_v) and clean_v is not None:
                    changes.append(_rec("data_types", sheet, int(idx), c,
                                        old_v, clean_v, f"Preserved {sem_type} as clean text without '.0'"))
            df[c] = new_col.astype("object")
            continue

        str_vals = non_null.astype(str).str.strip()

        # 4a Currency / comma / percentage → number
        if numeric_like_ratio(s) > 0.7:
            cleaned = str_vals.str.replace(CURRENCY_CHARS, "", regex=True)
            cleaned = cleaned.str.replace("%", "", regex=False)
            cleaned = cleaned.str.replace(r"^\((.+)\)$", r"-\1", regex=True)
            numeric = pd.to_numeric(cleaned, errors="coerce")
            converted_mask = numeric.notna() & (s.notna())
            for idx in converted_mask[converted_mask].index:
                old_v = s.at[idx]
                new_v = numeric.at[idx]
                if str(old_v) != str(new_v):
                    changes.append(_rec("data_types", sheet, int(idx), c,
                                        old_v, new_v, "Currency/comma → number"))
            df[c] = numeric
            continue

        # 4b Mixed date formats → real dates
        if date_like_ratio(s) > 0.7:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                dates = pd.to_datetime(s, errors="coerce", format="mixed")
            converted_mask = dates.notna() & s.notna()
            for idx in converted_mask[converted_mask].index:
                old_v = s.at[idx]
                new_v = dates.at[idx]
                if not isinstance(old_v, pd.Timestamp) and str(old_v) != str(new_v):
                    changes.append(_rec("data_types", sheet, int(idx), c,
                                        old_v, new_v, "Mixed date → datetime"))
            df[c] = dates
            continue

        # 4c yes/no → boolean
        lower_vals = str_vals.str.lower()
        if lower_vals.isin(_YES_NO.keys()).mean() > 0.8:
            for idx in non_null.index:
                old_v = s.at[idx]
                lv = str(old_v).strip().lower()
                if lv in _YES_NO:
                    new_v = _YES_NO[lv]
                    changes.append(_rec("data_types", sheet, int(idx), c,
                                        old_v, new_v, "Yes/No → boolean"))
                    df.at[idx, c] = new_v

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 5 — Value standardisation (fuzzy merge on categories)
# ────────────────────────────────────────────────────────────────────────────
def stage_value_standardisation(df: pd.DataFrame, sheet: str, **kwargs) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    for c in text_cols(df):
        s = df[c].dropna().astype(str).str.strip()
        if s.empty or s.nunique() > 300:
            continue
        vc = s.value_counts()
        vals = list(vc.index)
        mapping: dict[str, str] = {}
        for i, a in enumerate(vals):
            if a in mapping:
                continue
            for b in vals[i + 1:]:
                if b in mapping:
                    continue
                if a.lower() == b.lower() or fuzz.ratio(a.lower(), b.lower()) >= 85:
                    if vc.get(a, 0) >= vc.get(b, 0):
                        mapping[b] = a
                    else:
                        mapping[a] = b
        if mapping:
            for idx in df.index:
                v = df.at[idx, c]
                if pd.isna(v):
                    continue
                vs = str(v).strip()
                if vs in mapping:
                    new_v = mapping[vs]
                    changes.append(_rec("value_standardisation", sheet, int(idx), c,
                                        vs, new_v, f"Fuzzy merge: '{vs}' → '{new_v}'"))
                    df.at[idx, c] = new_v
    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 6 — Missing values (Semantic policy & derived formula detection)
# ────────────────────────────────────────────────────────────────────────────
def stage_missing_values(
    df: pd.DataFrame,
    sheet: str,
    semantics: dict[str, dict] | None = None,
    column_rules: dict[str, dict] | None = None,
    needs_review_items: list[dict] | None = None,
    left_blank_by_design: dict[str, dict] | None = None,
    **kwargs,
) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    semantics = semantics or infer_dataset_semantics(df)
    column_rules = column_rules or {}
    needs_review = needs_review_items if needs_review_items is not None else []
    left_blanks = left_blank_by_design if left_blank_by_design is not None else {}

    # 1. Drop rows/cols that are mostly empty (>= 80%) unless overridden
    row_thresh = 0.8 * df.shape[1]
    mostly_empty_rows = df.isna().sum(axis=1) >= row_thresh
    for idx in df.index[mostly_empty_rows]:
        changes.append(_rec("missing_values", sheet, int(idx), "*",
                            "(mostly empty row)", "(removed)",
                            f"Row {idx} is ≥80% empty"))
    df = df.loc[~mostly_empty_rows].reset_index(drop=True)

    # 2. Formula detection for derived columns (holding on >= 98% complete rows)
    formulas = detect_derived_formulas(df)
    formula_by_target = {f["target"]: f for f in formulas}

    # 3. Process each column with missing values
    for c in list(df.columns):
        null_mask = df[c].isna()
        null_count = int(null_mask.sum())
        if null_count == 0:
            continue

        sem_info = semantics.get(c, {})
        sem_type = sem_info.get("semantic_type", "other_text")
        policy = POLICY_MATRIX.get(sem_type, POLICY_MATRIX["other_text"])

        # Determine effective missing rule
        col_rule_cfg = column_rules.get(c, {}) or column_rules.get(_snake_case(c), {})
        missing_rule = col_rule_cfg.get("missing_rule") or policy["default_missing_rule"]

        # Check if derived formula should be used
        if (missing_rule == "fill_formula" or c in formula_by_target) and missing_rule != "leave_blank":
            frm = formula_by_target.get(c)
            if frm:
                fn = frm["fn"]
                expr = frm["expression"]
                inputs = frm["inputs"]
                filled_count = 0
                for idx in df.index[null_mask]:
                    # Check that inputs are non-null
                    if df.loc[idx, inputs].notna().all():
                        calc_val = fn(df.loc[[idx]]).iloc[0]
                        if pd.notna(calc_val):
                            changes.append(_rec("missing_values", sheet, int(idx), c,
                                                None, round(float(calc_val), 2),
                                                f"Calculated from formula {expr}"))
                            df.at[idx, c] = calc_val
                            filled_count += 1
                if filled_count > 0:
                    continue

        # RULE: identifier -> NEVER impute. Leave blank, flag for review, add to Needs_Review
        if sem_type == "identifier" or missing_rule == "flag_review":
            for idx in df.index[null_mask]:
                needs_review.append({
                    "sheet": sheet,
                    "row": int(idx),
                    "column": c,
                    "value": None,
                    "issue": f"Missing identifier in column '{c}'",
                    "action": "Review record and supply missing ID",
                    "stage": "review",
                })
            left_blanks[c] = {
                "count": null_count,
                "semantic_type": sem_type,
                "reason": "Missing identifier flagged for review; left blank by design",
            }
            continue

        # RULE: email, phone, url, postal_code, name, address, free_text, date, year, rating_scale, score/marks, percentage
        if missing_rule == "leave_blank":
            left_blanks[c] = {
                "count": null_count,
                "semantic_type": sem_type,
                "reason": f"Column type '{sem_type}' left blank by design policy",
            }
            continue

        # RULE: drop row option
        if missing_rule == "drop_row":
            drop_idxs = df.index[null_mask].tolist()
            for idx in drop_idxs:
                changes.append(_rec("missing_values", sheet, int(idx), c,
                                    "(missing)", "(removed)", f"Dropped row due to missing {c}"))
            df = df.loc[~null_mask].reset_index(drop=True)
            continue

        # RULE: fill unknown
        if missing_rule == "fill_unknown":
            for idx in df.index[null_mask]:
                changes.append(_rec("missing_values", sheet, int(idx), c,
                                    None, "Unknown", "Filled with 'Unknown'"))
            df[c] = df[c].fillna("Unknown")
            continue

        # RULE: fill zero
        if missing_rule == "fill_zero":
            for idx in df.index[null_mask]:
                changes.append(_rec("missing_values", sheet, int(idx), c,
                                    None, 0, "Filled with 0"))
            df[c] = df[c].fillna(0)
            continue

        # RULE: money_amount, quantity, other_numeric -> grouped median if group >= 5, else global median
        # Do NOT impute when column is > 30% missing
        null_pct = (null_count / len(df)) * 100.0 if len(df) else 0.0
        if sem_type in ("money_amount", "quantity", "other_numeric", "age") or missing_rule in ("fill_group_median", "fill_median"):
            if null_pct > 30.0 and missing_rule != "fill_median":
                left_blanks[c] = {
                    "count": null_count,
                    "semantic_type": sem_type,
                    "reason": f"Column '{c}' is {null_pct:.1f}% missing (>30% threshold); left blank by design + warn",
                }
                continue

            group_col = find_best_group_column(df, c, semantics) if missing_rule == "fill_group_median" else None
            global_med = df[c].median()
            if sem_type == "quantity":
                global_med = int(round(global_med)) if pd.notna(global_med) else 0

            if group_col:
                # Group median imputation
                for idx in df.index[null_mask]:
                    grp_val = df.at[idx, group_col]
                    grp_s = df.loc[df[group_col] == grp_val, c].dropna()
                    if len(grp_s) >= 5:
                        fill_v = grp_s.median()
                        if sem_type == "quantity":
                            fill_v = int(round(fill_v))
                        reason_msg = f"Filled with grouped median ({fill_v}) by '{group_col}'={grp_val}"
                    else:
                        fill_v = global_med
                        reason_msg = f"Filled with global median ({fill_v}) (group count < 5)"
                    changes.append(_rec("missing_values", sheet, int(idx), c, None, fill_v, reason_msg))
                    df.at[idx, c] = fill_v
            else:
                for idx in df.index[null_mask]:
                    changes.append(_rec("missing_values", sheet, int(idx), c, None, global_med,
                                        f"Filled with global median ({global_med})"))
                df[c] = df[c].fillna(global_med)
            continue

        # RULE: category, status, gender -> mode if < 5% missing & cardinality <= 20, else "Unknown"
        if missing_rule == "fill_mode_or_unknown":
            uniq_cnt = df[c].nunique(dropna=True)
            if null_pct < 5.0 and uniq_cnt <= 20:
                mode_vals = df[c].mode(dropna=True)
                fill_val = mode_vals.iloc[0] if len(mode_vals) else "Unknown"
                reason_msg = f"Filled with mode '{fill_val}' (<5% missing)"
            else:
                fill_val = "Unknown"
                reason_msg = f"Filled with 'Unknown' (missing pct {null_pct:.1f}% ≥ 5% or high cardinality)"

            for idx in df.index[null_mask]:
                changes.append(_rec("missing_values", sheet, int(idx), c, None, fill_val, reason_msg))
            df[c] = df[c].fillna(fill_val)
            continue

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 7 — Duplicates (Identifier conflict reporting & exact duplicates)
# ────────────────────────────────────────────────────────────────────────────
def stage_duplicates(
    df: pd.DataFrame,
    sheet: str,
    semantics: dict[str, dict] | None = None,
    needs_review_items: list[dict] | None = None,
    **kwargs,
) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    semantics = semantics or infer_dataset_semantics(df)
    needs_review = needs_review_items if needs_review_items is not None else []

    # Find identifier columns
    id_cols = [c for c in df.columns if semantics.get(c, {}).get("semantic_type") == "identifier"]

    if id_cols:
        # Check duplicates on identifier columns separately
        primary_id = id_cols[0]
        non_null_mask = df[primary_id].notna()
        id_series = df.loc[non_null_mask, primary_id]
        dup_ids = id_series[id_series.duplicated(keep=False)].unique()

        rows_to_drop = []
        for did in dup_ids:
            matching_rows = df[df[primary_id] == did]
            # Check if all rows are identical across all columns
            is_identical = len(matching_rows.drop_duplicates()) == 1
            if is_identical:
                # Same ID with identical rows -> drop duplicate
                sub_idxs = matching_rows.index.tolist()[1:]
                for idx in sub_idxs:
                    row_vals = df.loc[idx].to_dict()
                    changes.append(_rec("duplicates", sheet, int(idx), "*",
                                        str(row_vals), "(removed)",
                                        f"Exact duplicate ID '{did}' with identical data dropped"))
                    rows_to_drop.append(idx)
            else:
                # Same ID with DIFFERENT data -> do NOT auto-drop, report conflict in Needs_Review
                for idx in matching_rows.index:
                    needs_review.append({
                        "sheet": sheet,
                        "row": int(idx),
                        "column": primary_id,
                        "value": str(did),
                        "issue": f"Duplicate ID conflict: ID '{did}' has differing data across records",
                        "action": "Investigate and resolve conflicting records manually",
                        "stage": "review",
                    })

        if rows_to_drop:
            df = df.drop(index=rows_to_drop).reset_index(drop=True)

    # Also drop general exact duplicate rows across all columns
    dup_mask = df.duplicated(keep="first")
    dup_idxs = df.index[dup_mask].tolist()
    for idx in dup_idxs:
        row_vals = df.loc[idx].to_dict()
        changes.append(_rec("duplicates", sheet, int(idx), "*",
                            str(row_vals), "(removed)", "Exact duplicate row removed"))
    df = df.loc[~dup_mask].reset_index(drop=True)

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 8 — Outliers (Domain bounds checks & no clipping on protected columns)
# ────────────────────────────────────────────────────────────────────────────
DOMAIN_BOUNDS = {
    "age": (0, 120),
    "percentage": (0, 100),
    "quantity": (0, None),
    "money_amount": (0, None),
}


def stage_outliers(
    df: pd.DataFrame,
    sheet: str,
    semantics: dict[str, dict] | None = None,
    needs_review_items: list[dict] | None = None,
    **kwargs,
) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    semantics = semantics or infer_dataset_semantics(df)
    needs_review = needs_review_items if needs_review_items is not None else []

    # Protected columns: NEVER clip identifiers, phone, postal code, year, rating or percentage columns
    protected_types = {"identifier", "phone", "postal_code", "year", "rating_scale", "percentage", "score/marks"}

    for c in df.select_dtypes(include=[np.number]).columns:
        sem_type = semantics.get(c, {}).get("semantic_type", "other_numeric")
        if sem_type in protected_types:
            # Check domain bounds if applicable, but never clip
            if sem_type == "percentage":
                s = df[c].dropna()
                for idx in s.index:
                    v = s.at[idx]
                    if v < 0 or v > 100:
                        needs_review.append({
                            "sheet": sheet, "row": int(idx), "column": c, "value": v,
                            "issue": f"Percentage {v} out of bounds (0-100)",
                            "action": "Flagged for review; not clipped silently",
                            "stage": "review",
                        })
            continue

        # Check known domain bounds
        if sem_type in DOMAIN_BOUNDS:
            lo_b, hi_b = DOMAIN_BOUNDS[sem_type]
            s = df[c].dropna()
            for idx in s.index:
                v = s.at[idx]
                out_of_bounds = (lo_b is not None and v < lo_b) or (hi_b is not None and v > hi_b)
                if out_of_bounds:
                    bound_str = f"{lo_b}–{hi_b if hi_b is not None else '∞'}"
                    needs_review.append({
                        "sheet": sheet, "row": int(idx), "column": c, "value": v,
                        "issue": f"Value {v} out of domain bounds ({bound_str}) for {sem_type}",
                        "action": "Flagged for review; not clipped silently",
                        "stage": "review",
                    })
            continue

        # General other_numeric IQR clipping
        s = df[c].dropna()
        if len(s) < 8:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        for idx in df.index:
            v = df.at[idx, c]
            if pd.isna(v):
                continue
            if v < lo:
                changes.append(_rec("outliers", sheet, int(idx), c,
                                    v, lo, f"Outlier clipped to IQR lower bound ({lo:.2f})"))
                df.at[idx, c] = lo
            elif v > hi:
                changes.append(_rec("outliers", sheet, int(idx), c,
                                    v, hi, f"Outlier clipped to IQR upper bound ({hi:.2f})"))
                df.at[idx, c] = hi

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 9 — PII (Mask personal data)
# ────────────────────────────────────────────────────────────────────────────
def _mask_value(v: str, pii_type: str) -> str:
    if "@" in v:
        u, d = v.split("@", 1)
        return u[:1] + "***@" + d
    if len(v) >= 4:
        return v[0] + "*" * (len(v) - 3) + v[-2:]
    return "*" * max(len(v) - 2, 0) + v[-2:]


def stage_pii(df: pd.DataFrame, sheet: str, **kwargs) -> tuple[pd.DataFrame, list[dict]]:
    changes: list[dict] = []
    df = df.copy()
    for c in df.columns:
        pii_kind = detect_pii(df[c])
        if pii_kind is None:
            continue
        for idx in df.index:
            v = df.at[idx, c]
            if pd.isna(v):
                continue
            vs = str(v).strip()
            masked = _mask_value(vs, pii_kind)
            if masked != vs:
                changes.append(_rec("pii", sheet, int(idx), c,
                                    vs, masked, f"PII ({pii_kind}) masked"))
                df.at[idx, c] = masked
    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# STAGE 10 — Validation (Validity checks flag into Needs_Review)
# ────────────────────────────────────────────────────────────────────────────
def stage_validation(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    sheet: str,
    semantics: dict[str, dict] | None = None,
    needs_review_items: list[dict] | None = None,
    **kwargs,
) -> tuple[pd.DataFrame, list[dict], dict]:
    semantics = semantics or infer_dataset_semantics(df_after)
    needs_review = needs_review_items if needs_review_items is not None else []
    changes: list[dict] = []

    # Validity checks: email format, 10-digit phone, 6-digit pincode, negative quantity, marks > max
    email_rx = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
    phone_rx = re.compile(r"^\+?\d{10,12}$")
    pin_rx = re.compile(r"^\d{6}$")

    for c in df_after.columns:
        sem_type = semantics.get(c, {}).get("semantic_type", "")
        s = df_after[c].dropna()

        if sem_type == "email":
            for idx, val in s.items():
                val_s = str(val).strip()
                if val_s and not email_rx.match(val_s):
                    needs_review.append({
                        "sheet": sheet, "row": int(idx), "column": c, "value": val_s,
                        "issue": "Invalid email address format",
                        "action": "Flagged for review", "stage": "review",
                    })

        elif sem_type == "phone":
            for idx, val in s.items():
                digits = re.sub(r"\D", "", str(val))
                if len(digits) != 10:
                    needs_review.append({
                        "sheet": sheet, "row": int(idx), "column": c, "value": str(val),
                        "issue": f"Phone number has {len(digits)} digits (expected 10)",
                        "action": "Flagged for review", "stage": "review",
                    })

        elif sem_type == "postal_code":
            for idx, val in s.items():
                digits = re.sub(r"\D", "", str(val))
                if len(digits) != 6:
                    needs_review.append({
                        "sheet": sheet, "row": int(idx), "column": c, "value": str(val),
                        "issue": f"Postal code has {len(digits)} digits (expected 6-digit pincode)",
                        "action": "Flagged for review", "stage": "review",
                    })

        elif sem_type == "quantity":
            for idx, val in s.items():
                try:
                    num_v = float(val)
                    if num_v < 0:
                        needs_review.append({
                            "sheet": sheet, "row": int(idx), "column": c, "value": num_v,
                            "issue": "Negative quantity value",
                            "action": "Flagged for review", "stage": "review",
                        })
                except Exception:
                    pass

        elif sem_type == "score/marks":
            for idx, val in s.items():
                try:
                    num_v = float(val)
                    if num_v > 100:
                        needs_review.append({
                            "sheet": sheet, "row": int(idx), "column": c, "value": num_v,
                            "issue": f"Marks ({num_v}) exceeds standard maximum (100)",
                            "action": "Flagged for review", "stage": "review",
                        })
                except Exception:
                    pass

    prof_before = profile(df_before)
    prof_after = profile(df_after)
    quality_before = prof_before["quality"]
    quality_after = prof_after["quality"]

    changes.append(_rec("validation", sheet, "*", "*",
                        f"Score {quality_before['score']}",
                        f"Score {quality_after['score']}",
                        "Data-quality score recomputed"))

    return df_after, changes, {
        "before": quality_before,
        "after": quality_after,
    }


# ────────────────────────────────────────────────────────────────────────────
# STAGE REGISTRY
# ────────────────────────────────────────────────────────────────────────────
STAGE_FUNCTIONS: dict[str, Any] = {
    "structure":             stage_structure,
    "column_names":          stage_column_names,
    "text_hygiene":          stage_text_hygiene,
    "data_types":            stage_data_types,
    "value_standardisation": stage_value_standardisation,
    "missing_values":        stage_missing_values,
    "duplicates":            stage_duplicates,
    "outliers":              stage_outliers,
    "pii":                   stage_pii,
}


# ────────────────────────────────────────────────────────────────────────────
# PIPELINE RUNNER
# ────────────────────────────────────────────────────────────────────────────
def run_pipeline(
    df: pd.DataFrame,
    sheet_name: str = "Sheet1",
    skip: list[str] | None = None,
    column_rules: dict[str, dict] | None = None,
    semantics_overrides: dict[str, str] | None = None,
) -> dict:
    """
    Run the 10-stage Column-Aware Auto-Clean Pipeline in order.
    """
    skip = set(skip or [])
    original_df = df.copy()
    all_changes: list[dict] = []
    removed_rows: list[dict] = []
    needs_review_items: list[dict] = []
    left_blank_by_design: dict[str, dict] = {}
    stage_summaries: list[dict] = []
    current = df.copy()

    # Initial semantic inference
    overrides = semantics_overrides or {}
    if column_rules:
        for col_name, rule_cfg in column_rules.items():
            if rule_cfg.get("semantic_type"):
                overrides[col_name] = rule_cfg["semantic_type"]
    semantics = infer_dataset_semantics(df, overrides=overrides)

    for stage_key in STAGE_ORDER:
        if stage_key in skip:
            stage_summaries.append({
                "stage": stage_key,
                "status": "skipped",
                "changes": 0,
                "colour": f"#{STAGE_COLOURS[stage_key]['hex']}",
                "label": STAGE_COLOURS[stage_key]["label"],
            })
            continue

        if stage_key == "validation":
            current, v_changes, quality_cmp = stage_validation(
                original_df, current, sheet_name, semantics=semantics,
                needs_review_items=needs_review_items,
            )
            all_changes.extend(v_changes)
            stage_summaries.append({
                "stage": stage_key,
                "status": "done",
                "changes": len(v_changes),
                "colour": f"#{STAGE_COLOURS[stage_key]['hex']}",
                "label": STAGE_COLOURS[stage_key]["label"],
                "quality": quality_cmp,
            })
            continue

        fn = STAGE_FUNCTIONS[stage_key]
        rows_before = len(current)

        # Pass semantic and rule context into stages
        current, changes = fn(
            current,
            sheet_name,
            semantics=semantics,
            column_rules=column_rules,
            needs_review_items=needs_review_items,
            left_blank_by_design=left_blank_by_design,
        )
        rows_after = len(current)

        # Track removed rows
        if stage_key in ("structure", "missing_values", "duplicates"):
            for ch in changes:
                if "(removed)" in str(ch.get("new_value", "")):
                    removed_rows.append(ch)

        # Update semantics if columns were renamed
        if stage_key == "column_names":
            semantics = infer_dataset_semantics(current, overrides=overrides)

        all_changes.extend(changes)
        stage_summaries.append({
            "stage": stage_key,
            "status": "done",
            "changes": len(changes),
            "rows_before": rows_before,
            "rows_after": rows_after,
            "colour": f"#{STAGE_COLOURS[stage_key]['hex']}",
            "label": STAGE_COLOURS[stage_key]["label"],
        })

    # Review count
    review_count = len(needs_review_items)

    # Quality comparison
    val_summary = next((s for s in stage_summaries if s["stage"] == "validation"), None)
    if val_summary and "quality" in val_summary:
        quality_cmp = val_summary["quality"]
    else:
        prof_before = profile(original_df)
        prof_after = profile(current)
        quality_cmp = {
            "before": prof_before["quality"],
            "after": prof_after["quality"],
        }

    # Currencies
    column_currencies: dict[str, str] = {}
    for c in original_df.columns:
        s_vals = original_df[c].dropna().astype(str)
        if not s_vals.empty:
            for sym in ["₹", "$", "€", "£", "¥"]:
                if s_vals.str.contains(sym, regex=False).any():
                    column_currencies[c] = sym
                    break

    return {
        "cleaned_df": current,
        "all_changes": all_changes,
        "removed_rows": removed_rows,
        "needs_review_items": needs_review_items,
        "left_blank_by_design": left_blank_by_design,
        "stage_summaries": stage_summaries,
        "quality_comparison": quality_cmp,
        "column_currencies": column_currencies,
        "semantics": semantics,
    }


# ────────────────────────────────────────────────────────────────────────────
# EXCEL EXPORT — Multi-sheet workbook with Needs_Review & design counts
# ────────────────────────────────────────────────────────────────────────────
def _fill(hex_colour: str) -> PatternFill:
    return PatternFill(start_color=hex_colour, end_color=hex_colour, fill_type="solid")


def _write_df_to_sheet(ws, df: pd.DataFrame, semantics: dict[str, dict] | None = None, is_cleaned_data: bool = False):
    """Write DataFrame with strict types, formatted dates, text IDs preserved without scientific notation."""
    semantics = semantics or {}
    header_font = Font(bold=True)
    for col_idx, col_name in enumerate(df.columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=str(col_name))
        cell.font = header_font
        if not is_cleaned_data:
            cell.fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")

    for row_idx, (_, row) in enumerate(df.iterrows(), 2):
        for col_idx, (col_name, val) in enumerate(row.items(), 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            sem_type = semantics.get(col_name, {}).get("semantic_type", "")

            if pd.isna(val) or (isinstance(val, float) and np.isnan(val)):
                cell.value = None
            elif sem_type in ("identifier", "phone", "postal_code") or "id" in str(col_name).lower():
                # Strictly plain text (keep leading zeros, no .0)
                str_val = str(val)
                if str_val.endswith(".0"):
                    str_val = str_val[:-2]
                cell.value = str_val
                cell.number_format = "@"
            elif isinstance(val, (pd.Timestamp, np.datetime64)):
                cell.value = val.to_pydatetime() if hasattr(val, "to_pydatetime") else val
                cell.number_format = "yyyy-mm-dd"
            elif isinstance(val, (_dt.datetime, _dt.date)):
                cell.value = val
                cell.number_format = "yyyy-mm-dd"
            elif isinstance(val, (bool, np.bool_)):
                cell.value = bool(val)
            elif isinstance(val, (int, np.integer)):
                cell.value = int(val)
            elif isinstance(val, (float, np.floating)):
                cell.value = float(val)
            else:
                cell.value = str(val)

    if is_cleaned_data:
        ws.freeze_panes = "A2"
        last_col = get_column_letter(max(1, df.shape[1]))
        ws.auto_filter.ref = f"A1:{last_col}{max(2, len(df) + 1)}"

    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            max_len = max(max_len, len(str(cell.value or "")))
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)


def build_export_workbook(
    cleaned_df: pd.DataFrame,
    all_changes: list[dict],
    removed_rows: list[dict],
    stage_summaries: list[dict],
    quality_comparison: dict,
    needs_review_items: list[dict] | None = None,
    left_blank_by_design: dict[str, dict] | None = None,
    sheet_name: str = "Sheet1",
    semantics: dict[str, dict] | None = None,
    raw_df: pd.DataFrame | None = None,
) -> bytes:
    """
    Build the final multi-sheet Excel workbook with:
      Raw Data (Tab 1), Processed Data (Tab 2), Cleaned_Highlighted, Change_Log, Needs_Review, Removed_Rows, Summary, Legend.
    """
    wb = Workbook()
    needs_review = needs_review_items or []
    left_blanks = left_blank_by_design or {}
    semantics = semantics or infer_dataset_semantics(cleaned_df)

    # ── 1. Raw Data & 2. Processed Data (Cleaned_Data) ──
    if raw_df is not None:
        ws_raw = wb.active
        ws_raw.title = "Raw Data"
        _write_df_to_sheet(ws_raw, raw_df, semantics=semantics, is_cleaned_data=False)

        ws_clean = wb.create_sheet("Cleaned_Data")
        _write_df_to_sheet(ws_clean, cleaned_df, semantics=semantics, is_cleaned_data=True)
    else:
        ws_clean = wb.active
        ws_clean.title = "Cleaned_Data"
        _write_df_to_sheet(ws_clean, cleaned_df, semantics=semantics, is_cleaned_data=True)

    # ── 3. Cleaned_Highlighted ──
    ws_hl = wb.create_sheet("Cleaned_Highlighted")
    _write_df_to_sheet(ws_hl, cleaned_df, semantics=semantics, is_cleaned_data=False)

    col_list = list(cleaned_df.columns)
    change_map: dict[tuple[int, str], list[dict]] = {}
    for ch in all_changes:
        key = (ch.get("row"), ch.get("column"))
        if key[0] == "*" or key[1] == "*":
            continue
        try:
            row_i = int(key[0])
            change_map.setdefault((row_i, key[1]), []).append(ch)
        except (ValueError, TypeError):
            continue

    # Also map needs_review items for pink highlight
    review_map: dict[tuple[int, str], list[dict]] = {}
    for rv in needs_review:
        r_row = rv.get("row")
        r_col = rv.get("column")
        if r_row is not None and r_col:
            try:
                review_map.setdefault((int(r_row), r_col), []).append(rv)
            except Exception:
                pass

    for (row_i, col_name), chg_list in change_map.items():
        if col_name not in col_list:
            continue
        col_i = col_list.index(col_name) + 1
        xl_row = row_i + 2
        if xl_row < 2 or xl_row > len(cleaned_df) + 1:
            continue

        cell = ws_hl.cell(row=xl_row, column=col_i)
        last_stage = chg_list[-1]["stage"]
        colour_hex = STAGE_COLOURS.get(last_stage, {}).get("hex", "FFFFFF")
        cell.fill = _fill(colour_hex)

        marker = STAGE_COLOURS.get(last_stage, {}).get("marker", "")
        comment_lines = [f"{marker} {ch['reason']}" for ch in chg_list]
        cell.comment = Comment("\n".join(comment_lines), "DataPilot Pipeline")

    # Apply Pink Flagged for Review highlight
    pink_fill = _fill("FFB6C1")
    for (row_i, col_name), rv_list in review_map.items():
        if col_name not in col_list:
            continue
        col_i = col_list.index(col_name) + 1
        xl_row = row_i + 2
        if xl_row < 2 or xl_row > len(cleaned_df) + 1:
            continue
        cell = ws_hl.cell(row=xl_row, column=col_i)
        cell.fill = pink_fill
        rv_issues = " • ".join(rv["issue"] for rv in rv_list)
        cell.comment = Comment(f"[?] Flagged for review: {rv_issues}", "DataPilot Pipeline")
        cur_v = cell.value
        if cur_v is not None and not str(cur_v).startswith("["):
            cell.value = f"[?] {cur_v}"

    # ── 3. Change_Log ──
    ws_log = wb.create_sheet("Change_Log")
    log_headers = ["Stage", "Sheet", "Row", "Column", "Old Value", "New Value", "Reason"]
    for col_i, h in enumerate(log_headers, 1):
        cell = ws_log.cell(row=1, column=col_i, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")

    for row_i, ch in enumerate(all_changes, 2):
        stg = ch.get("stage", "")
        ws_log.cell(row=row_i, column=1, value=stg)
        ws_log.cell(row=row_i, column=2, value=ch.get("sheet", ""))
        ws_log.cell(row=row_i, column=3, value=str(ch.get("row", "")))
        ws_log.cell(row=row_i, column=4, value=ch.get("column", ""))
        ws_log.cell(row=row_i, column=5, value=ch.get("old_value"))
        ws_log.cell(row=row_i, column=6, value=ch.get("new_value"))
        ws_log.cell(row=row_i, column=7, value=ch.get("reason", ""))
        colour_hex = STAGE_COLOURS.get(stg, {}).get("hex", "FFFFFF")
        for col_i in range(1, 8):
            ws_log.cell(row=row_i, column=col_i).fill = _fill(colour_hex)

    # ── 4. Needs_Review Sheet ──
    ws_rev = wb.create_sheet("Needs_Review")
    rev_headers = ["Sheet", "Row", "Column", "Value", "Issue / Reason", "Recommended Action"]
    for col_i, h in enumerate(rev_headers, 1):
        cell = ws_rev.cell(row=1, column=col_i, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="FFD1DC", end_color="FFD1DC", fill_type="solid")

    for row_i, rv in enumerate(needs_review, 2):
        ws_rev.cell(row=row_i, column=1, value=rv.get("sheet", sheet_name))
        ws_rev.cell(row=row_i, column=2, value=str(rv.get("row", "")))
        ws_rev.cell(row=row_i, column=3, value=str(rv.get("column", "")))
        ws_rev.cell(row=row_i, column=4, value=str(rv.get("value", "")))
        ws_rev.cell(row=row_i, column=5, value=rv.get("issue", ""))
        ws_rev.cell(row=row_i, column=6, value=rv.get("action", ""))
        for col_i in range(1, 7):
            ws_rev.cell(row=row_i, column=col_i).fill = _fill("FFB6C1")

    # ── 5. Removed_Rows ──
    ws_rem = wb.create_sheet("Removed_Rows")
    rem_headers = ["Stage", "Sheet", "Row", "Details", "Reason"]
    for col_i, h in enumerate(rem_headers, 1):
        cell = ws_rem.cell(row=1, column=col_i, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")

    red_fill = _fill("FF0000")
    white_font = Font(color="FFFFFF")
    for row_i, ch in enumerate(removed_rows, 2):
        ws_rem.cell(row=row_i, column=1, value=ch.get("stage", ""))
        ws_rem.cell(row=row_i, column=2, value=ch.get("sheet", ""))
        ws_rem.cell(row=row_i, column=3, value=str(ch.get("row", "")))
        ws_rem.cell(row=row_i, column=4, value=ch.get("old_value"))
        ws_rem.cell(row=row_i, column=5, value=ch.get("reason", ""))
        for col_i in range(1, 6):
            cell = ws_rem.cell(row=row_i, column=col_i)
            cell.fill = red_fill
            cell.font = white_font

    # ── 6. Summary ──
    ws_sum = wb.create_sheet("Summary")
    ws_sum.cell(row=1, column=1, value="Stage").font = Font(bold=True)
    ws_sum.cell(row=1, column=2, value="Status").font = Font(bold=True)
    ws_sum.cell(row=1, column=3, value="Changes / Count").font = Font(bold=True)
    ws_sum.cell(row=1, column=4, value="Colour").font = Font(bold=True)
    for col_i in range(1, 5):
        ws_sum.cell(row=1, column=col_i).fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")

    cur_row = 2
    for ss in stage_summaries:
        ws_sum.cell(row=cur_row, column=1, value=ss["stage"])
        ws_sum.cell(row=cur_row, column=2, value=ss.get("status", ""))
        ws_sum.cell(row=cur_row, column=3, value=ss.get("changes", 0))
        colour_hex = ss.get("colour", "#FFFFFF").lstrip("#")
        ws_sum.cell(row=cur_row, column=4, value=STAGE_COLOURS.get(ss["stage"], {}).get("name", ""))
        ws_sum.cell(row=cur_row, column=4).fill = _fill(colour_hex)
        cur_row += 1

    # Quality comparison
    cur_row += 2
    ws_sum.cell(row=cur_row, column=1, value="Quality Score").font = Font(bold=True)
    if quality_comparison:
        ws_sum.cell(row=cur_row + 1, column=1, value="Before")
        ws_sum.cell(row=cur_row + 1, column=2, value=quality_comparison.get("before", {}).get("score", ""))
        ws_sum.cell(row=cur_row + 2, column=1, value="After")
        ws_sum.cell(row=cur_row + 2, column=2, value=quality_comparison.get("after", {}).get("score", ""))
        cur_row += 3

    # Section: Cells left blank on purpose
    cur_row += 1
    ws_sum.cell(row=cur_row, column=1, value="Cells Left Blank by Design").font = Font(bold=True)
    cur_row += 1
    if left_blanks:
        for c_name, lb_info in left_blanks.items():
            line = f"left blank by design: {lb_info.get('count', 0)} cells in {c_name} ({lb_info.get('semantic_type', 'unknown')})"
            ws_sum.cell(row=cur_row, column=1, value=line)
            ws_sum.cell(row=cur_row, column=2, value=lb_info.get("reason", ""))
            cur_row += 1
    else:
        ws_sum.cell(row=cur_row, column=1, value="None (all missing cells were imputed or clean)")
        cur_row += 1

    cur_row += 1
    ws_sum.cell(row=cur_row, column=1, value="Generated by DataPilot — Automated Data Cleaning & Governance").font = Font(bold=True, italic=True, color="2563EB")

    # ── 7. Legend ──
    ws_leg = wb.create_sheet("Legend")
    ws_leg.cell(row=1, column=1, value="Colour").font = Font(bold=True)
    ws_leg.cell(row=1, column=2, value="Meaning").font = Font(bold=True)
    ws_leg.cell(row=1, column=3, value="Marker").font = Font(bold=True)
    for col_i in range(1, 4):
        ws_leg.cell(row=1, column=col_i).fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")

    legend_items = get_legend()
    for row_i, item in enumerate(legend_items, 2):
        hex_c = item["colour_hex"].lstrip("#")
        ws_leg.cell(row=row_i, column=1, value=item["colour_name"])
        ws_leg.cell(row=row_i, column=1).fill = _fill(hex_c)
        ws_leg.cell(row=row_i, column=2, value=item["label"])
        ws_leg.cell(row=row_i, column=3, value=item["marker"])

    # Auto-fit column widths
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val_len = len(str(cell.value or ""))
                max_len = max(max_len, min(val_len, 50))
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
