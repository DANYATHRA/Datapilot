"""
Semantic Missing-Value Policy and Derived Column Detection.
Defines default actions, allowed actions, and execution strategies per semantic type.
"""
from __future__ import annotations

import re
from typing import Any, Callable

import numpy as np
import pandas as pd

# ────────────────────────────────────────────────────────────────────────────
# POLICY MATRIX — Single source of truth for missing & invalid policies
# ────────────────────────────────────────────────────────────────────────────
POLICY_MATRIX: dict[str, dict[str, Any]] = {
    "identifier": {
        "default_missing_rule": "flag_review",
        "allowed_missing_rules": ["flag_review", "leave_blank", "drop_row"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never impute. Leave blank, flag for review. Moves row to Needs_Review.",
    },
    "name": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_unknown", "flag_review", "drop_row"],
        "default_invalid_rule": "keep",
        "allowed_invalid_rules": ["flag", "keep"],
        "can_impute": False,
        "description": "Never impute statistical values; optionally fill with 'Unknown'.",
    },
    "email": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "flag_review", "drop_row"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never impute. Leave blank or flag invalid email formats.",
    },
    "phone": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "flag_review", "drop_row"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never impute. Format kept as plain text (leading zeros preserved).",
    },
    "postal_code": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "flag_review"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never impute. Kept as text.",
    },
    "url": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "flag_review"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never impute. Kept as text.",
    },
    "address/free_text": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_unknown"],
        "default_invalid_rule": "keep",
        "allowed_invalid_rules": ["keep"],
        "can_impute": False,
        "description": "Never impute free text.",
    },
    "date": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "flag_review", "drop_row"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never mean-fill. Leave blank by default.",
    },
    "year": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_median", "flag_review"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Never mean-fill. Keep blank unless overridden.",
    },
    "rating_scale": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_group_median", "fill_median"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Leave blank by default (analyses exclude blanks).",
    },
    "score/marks": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_group_median", "fill_median", "fill_zero"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Leave blank by default so absence is not conflated with zero or median.",
    },
    "percentage": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_zero", "fill_median"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": False,
        "description": "Leave blank unless a user rule says 0.",
    },
    "money_amount": {
        "default_missing_rule": "fill_group_median",
        "allowed_missing_rules": ["fill_group_median", "fill_median", "leave_blank", "fill_formula"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": True,
        "description": "Grouped median when group >= 5, else global median; no fill if >30% missing.",
    },
    "quantity": {
        "default_missing_rule": "fill_group_median",
        "allowed_missing_rules": ["fill_group_median", "fill_median", "leave_blank", "fill_zero", "fill_formula"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": True,
        "description": "Grouped integer median when group >= 5; no fill if >30% missing.",
    },
    "age": {
        "default_missing_rule": "fill_median",
        "allowed_missing_rules": ["fill_median", "fill_group_median", "leave_blank"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": True,
        "description": "Median integer age.",
    },
    "category": {
        "default_missing_rule": "fill_mode_or_unknown",
        "allowed_missing_rules": ["fill_mode_or_unknown", "fill_unknown", "leave_blank"],
        "default_invalid_rule": "keep",
        "allowed_invalid_rules": ["keep"],
        "can_impute": True,
        "description": "Mode if <5% missing and low cardinality, otherwise 'Unknown'.",
    },
    "gender": {
        "default_missing_rule": "fill_unknown",
        "allowed_missing_rules": ["fill_unknown", "leave_blank", "fill_mode_or_unknown"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "keep"],
        "can_impute": False,
        "description": "Fill with 'Unknown' or leave blank; never invent gender.",
    },
    "status/boolean_flag": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_mode_or_unknown"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "keep"],
        "can_impute": False,
        "description": "Leave blank.",
    },
    "other_numeric": {
        "default_missing_rule": "fill_group_median",
        "allowed_missing_rules": ["fill_group_median", "fill_median", "leave_blank", "fill_formula"],
        "default_invalid_rule": "flag",
        "allowed_invalid_rules": ["flag", "blank", "keep"],
        "can_impute": True,
        "description": "Grouped median if group >= 5, else global median; no fill if >30% missing.",
    },
    "other_text": {
        "default_missing_rule": "leave_blank",
        "allowed_missing_rules": ["leave_blank", "fill_unknown"],
        "default_invalid_rule": "keep",
        "allowed_invalid_rules": ["keep"],
        "can_impute": False,
        "description": "Leave blank.",
    },
}


# ────────────────────────────────────────────────────────────────────────────
# FORMULA DETECTION FOR DERIVED COLUMNS (>= 98% complete rows match)
# ────────────────────────────────────────────────────────────────────────────
def detect_derived_formulas(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Detect mathematical relationships between columns that hold on >= 98% of complete rows.
    Supports:
      1) total = units * unit_price * (1 - discount/100) or (1 - discount)
      2) c = a * b
      3) c = a + b
      4) c = a - b
    """
    num_cols = list(df.select_dtypes(include=[np.number]).columns)
    if len(num_cols) < 2:
        return []

    formulas = []

    # Check units * price * (1 - discount/100) pattern
    for target in num_cols:
        target_name = target.lower()
        if any(w in target_name for w in ["revenue", "total", "amount", "final"]):
            unit_col = next((c for c in num_cols if any(k in c.lower() for k in ["unit", "qty", "quantity"]) and c != target), None)
            price_col = next((c for c in num_cols if any(k in c.lower() for k in ["price", "cost", "rate"]) and c != target), None)
            disc_col = next((c for c in num_cols if any(k in c.lower() for k in ["disc", "pct", "percent"]) and c != target), None)

            if unit_col and price_col:
                # With discount
                if disc_col:
                    mask = df[[target, unit_col, price_col, disc_col]].notna().all(axis=1)
                    if mask.sum() >= 3:
                        sub = df.loc[mask]
                        # Check percentage (0-100) vs decimal (0-1)
                        is_pct_scale = sub[disc_col].max() > 1.0
                        divisor = 100.0 if is_pct_scale else 1.0
                        calc = sub[unit_col] * sub[price_col] * (1.0 - sub[disc_col] / divisor)
                        diff = (sub[target] - calc).abs()
                        match_rate = float((diff <= 0.05).mean())
                        if match_rate >= 0.98:
                            formula_desc = f"{unit_col} * {price_col} * (1 - {disc_col}/100)" if is_pct_scale else f"{unit_col} * {price_col} * (1 - {disc_col})"
                            formulas.append({
                                "target": target,
                                "expression": formula_desc,
                                "fn": lambda d, u=unit_col, p=price_col, dc=disc_col, div=divisor: d[u] * d[p] * (1.0 - d[dc] / div),
                                "inputs": [unit_col, price_col, disc_col],
                                "confidence": match_rate,
                            })
                            continue

                # Without discount: total = units * price
                mask = df[[target, unit_col, price_col]].notna().all(axis=1)
                if mask.sum() >= 3:
                    sub = df.loc[mask]
                    calc = sub[unit_col] * sub[price_col]
                    diff = (sub[target] - calc).abs()
                    match_rate = float((diff <= 0.05).mean())
                    if match_rate >= 0.98:
                        formulas.append({
                            "target": target,
                            "expression": f"{unit_col} * {price_col}",
                            "fn": lambda d, u=unit_col, p=price_col: d[u] * d[p],
                            "inputs": [unit_col, price_col],
                            "confidence": match_rate,
                        })
                        continue

    # Pairwise sum / diff / product checks
    for i, c_target in enumerate(num_cols):
        if any(f["target"] == c_target for f in formulas):
            continue
        for j, c_a in enumerate(num_cols):
            if c_a == c_target:
                continue
            for k, c_b in enumerate(num_cols[j + 1:], j + 1):
                if c_b == c_target:
                    continue

                mask = df[[c_target, c_a, c_b]].notna().all(axis=1)
                if mask.sum() < 3:
                    continue
                sub = df.loc[mask]
                target_val = sub[c_target]

                # 1) c = a * b
                prod_diff = (target_val - (sub[c_a] * sub[c_b])).abs()
                if (prod_diff <= 0.05).mean() >= 0.98:
                    formulas.append({
                        "target": c_target,
                        "expression": f"{c_a} * {c_b}",
                        "fn": lambda d, a=c_a, b=c_b: d[a] * d[b],
                        "inputs": [c_a, c_b],
                        "confidence": float((prod_diff <= 0.05).mean()),
                    })
                    break

                # 2) c = a + b
                sum_diff = (target_val - (sub[c_a] + sub[c_b])).abs()
                if (sum_diff <= 0.05).mean() >= 0.98:
                    formulas.append({
                        "target": c_target,
                        "expression": f"{c_a} + {c_b}",
                        "fn": lambda d, a=c_a, b=c_b: d[a] + d[b],
                        "inputs": [c_a, c_b],
                        "confidence": float((sum_diff <= 0.05).mean()),
                    })
                    break

                # 3) c = a - b
                diff_val = (target_val - (sub[c_a] - sub[c_b])).abs()
                if (diff_val <= 0.05).mean() >= 0.98:
                    formulas.append({
                        "target": c_target,
                        "expression": f"{c_a} - {c_b}",
                        "fn": lambda d, a=c_a, b=c_b: d[a] - d[b],
                        "inputs": [c_a, c_b],
                        "confidence": float((diff_val <= 0.05).mean()),
                    })
                    break

    return formulas


# ────────────────────────────────────────────────────────────────────────────
# BEST GROUPING COLUMN HEURISTIC
# ────────────────────────────────────────────────────────────────────────────
def find_best_group_column(df: pd.DataFrame, target_col: str, semantics: dict[str, dict] | None = None) -> str | None:
    """Find the best categorical column to group by for group-median imputation."""
    semantics = semantics or {}
    candidates = []
    for col in df.columns:
        if col == target_col:
            continue
        sem = semantics.get(col, {}).get("semantic_type", "")
        uniq = df[col].nunique(dropna=True)
        if sem in ("category", "gender", "status/boolean_flag") or (not pd.api.types.is_numeric_dtype(df[col]) and 2 <= uniq <= 30):
            if 2 <= uniq <= 30:
                candidates.append((col, uniq))
    if not candidates:
        return None
    # Prefer moderate cardinality (between 3 and 15 groups)
    candidates.sort(key=lambda x: abs(x[1] - 6))
    return candidates[0][0]


# ────────────────────────────────────────────────────────────────────────────
# PLAIN-LANGUAGE PREVIEW LINE
# ────────────────────────────────────────────────────────────────────────────
def get_preview_line(
    col: str,
    null_count: int,
    semantic_type: str,
    missing_rule: str,
    group_col: str | None = None,
    formula_expr: str | None = None,
) -> str:
    """Generate the exact plain-language preview line describing the missing value action."""
    if null_count == 0:
        return f"{col}: Complete (0 missing values)"

    s_plural = "s" if null_count != 1 else ""

    if missing_rule in ("flag_review", "leave_blank"):
        if semantic_type == "identifier" or missing_rule == "flag_review":
            return f"{col}: {null_count} blank{s_plural} will stay blank and be listed in Needs_Review"
        return f"{col}: {null_count} blank{s_plural} will stay blank"

    if missing_rule == "fill_formula":
        expr_str = f" formula {formula_expr}" if formula_expr else " derived formula"
        return f"{col}: {null_count} blank{s_plural} will be calculated from{expr_str}"

    if missing_rule == "fill_group_median":
        grp_str = f" of the same group (by '{group_col}')" if group_col else ""
        return f"{col}: {null_count} blank{s_plural} will be filled with median{grp_str}"

    if missing_rule == "fill_median":
        return f"{col}: {null_count} blank{s_plural} will be filled with median"

    if missing_rule == "fill_mode_or_unknown":
        return f"{col}: {null_count} blank{s_plural} will be filled with most common value (<5% missing) or 'Unknown'"

    if missing_rule == "fill_unknown":
        return f"{col}: {null_count} blank{s_plural} will be filled with 'Unknown'"

    if missing_rule == "fill_zero":
        return f"{col}: {null_count} blank{s_plural} will be filled with 0"

    if missing_rule == "drop_row":
        return f"{col}: {null_count} row{s_plural} with missing values will be dropped"

    return f"{col}: {null_count} blank{s_plural} handled by policy '{missing_rule}'"
