"""Data Quality Scorecard engine.

Dimensions: completeness, uniqueness, validity, consistency, timeliness,
accuracy-by-rule.

Rule builder (no-code): not null, unique, allowed values, range, regex,
date not in future, referential integrity, cross-column rules.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..db import db

# ── MongoDB collection ─────────────────────────────────────────────
quality_rules = db["quality_rules"]
quality_reports = db["quality_reports"]

# ── Rule types ─────────────────────────────────────────────────────
RULE_TYPES = {
    "not_null": "Column must not contain null values",
    "unique": "All values in the column must be unique",
    "allowed_values": "Values must be in a specified list",
    "range": "Numeric values must be within min/max bounds",
    "regex": "Values must match a regular expression pattern",
    "date_not_future": "Date values must not be in the future",
    "referential_integrity": "Values must exist in a reference column of another table",
    "cross_column": "Cross-column expression must evaluate to True (e.g., end >= start)",
}

SEVERITY_LEVELS = ("critical", "warning", "info")


# ── Rule evaluation ───────────────────────────────────────────────
def evaluate_rule(df: pd.DataFrame, rule: dict, ref_df: pd.DataFrame | None = None) -> dict:
    """Evaluate a single rule against a DataFrame.

    Returns dict with: passed (bool), fail_count, total, fail_pct, sample_rows, suggested_fix.
    """
    rule_type = rule.get("type") or rule.get("rule_type", "")
    column = rule.get("column", "")
    params = rule.get("params", {})

    if column and column not in df.columns:
        return {"passed": None, "fail_count": 0, "total": 0, "fail_pct": 0,
                "sample_rows": [], "error": f"Column '{column}' not found"}

    series = df[column] if column else None
    total = len(df)
    fail_mask = pd.Series(False, index=df.index)

    try:
        if rule_type == "not_null":
            fail_mask = series.isna()

        elif rule_type == "unique":
            fail_mask = series.duplicated(keep=False) & series.notna()

        elif rule_type == "allowed_values":
            allowed = set(params.get("values", []))
            fail_mask = ~series.isin(allowed) & series.notna()

        elif rule_type == "range":
            min_val = params.get("min")
            max_val = params.get("max")
            numeric = pd.to_numeric(series, errors="coerce")
            if min_val is not None:
                fail_mask = fail_mask | (numeric < float(min_val))
            if max_val is not None:
                fail_mask = fail_mask | (numeric > float(max_val))
            fail_mask = fail_mask & numeric.notna()

        elif rule_type == "regex":
            pattern = params.get("pattern", "")
            if pattern:
                rx = re.compile(pattern)
                vals = series.dropna().astype(str)
                match_result = vals.map(lambda x: bool(rx.fullmatch(x)))
                fail_mask = pd.Series(False, index=df.index)
                fail_mask.loc[vals.index] = ~match_result

        elif rule_type == "date_not_future":
            dt = pd.to_datetime(series, errors="coerce")
            now = pd.Timestamp.now(tz="UTC").tz_localize(None)
            fail_mask = dt > now

        elif rule_type == "referential_integrity":
            ref_col = params.get("ref_column", "")
            if ref_df is not None and ref_col in ref_df.columns:
                ref_values = set(ref_df[ref_col].dropna().unique())
                fail_mask = ~series.isin(ref_values) & series.notna()
            else:
                return {"passed": None, "fail_count": 0, "total": total, "fail_pct": 0,
                        "sample_rows": [], "error": "Reference table/column not available"}

        elif rule_type == "cross_column":
            expr = params.get("expression", "")
            if expr:
                try:
                    result = df.eval(expr)
                    fail_mask = ~result.astype(bool)
                    fail_mask = fail_mask.fillna(False)
                except Exception as e:
                    return {"passed": None, "fail_count": 0, "total": total, "fail_pct": 0,
                            "sample_rows": [], "error": f"Expression error: {e}"}
        else:
            return {"passed": None, "fail_count": 0, "total": total, "fail_pct": 0,
                    "sample_rows": [], "error": f"Unknown rule type: {rule_type}"}

    except Exception as e:
        return {"passed": None, "fail_count": 0, "total": total, "fail_pct": 0,
                "sample_rows": [], "error": str(e)}

    fail_count = int(fail_mask.sum())
    fail_pct = round(fail_count / total * 100, 2) if total else 0
    sample_idx = fail_mask[fail_mask].head(5).index.tolist()
    sample_rows = []
    for idx in sample_idx:
        row = {}
        for c in df.columns[:10]:
            val = df.at[idx, c]
            row[c] = None if pd.isna(val) else str(val) if not isinstance(val, (int, float)) else val
        row["_row_index"] = int(idx)
        sample_rows.append(row)

    suggested_fix = _suggest_fix(rule_type, column, fail_count, params)

    return {
        "passed": fail_count == 0,
        "fail_count": fail_count,
        "total": total,
        "fail_pct": fail_pct,
        "sample_rows": sample_rows,
        "suggested_fix": suggested_fix,
    }


def _suggest_fix(rule_type: str, column: str, fail_count: int, params: dict) -> str:
    """Generate a human-readable suggested fix for a failing rule."""
    if fail_count == 0:
        return ""
    fixes = {
        "not_null": f"Fill or remove {fail_count} null values in '{column}' → Clean & prepare → Fill missing",
        "unique": f"Remove or merge {fail_count} duplicate values in '{column}' → Clean & prepare → Deduplicate",
        "allowed_values": f"Correct {fail_count} invalid values in '{column}' to allowed set → Clean & prepare → Map values",
        "range": f"Fix {fail_count} out-of-range values in '{column}' → Clean & prepare → Clip or filter",
        "regex": f"Fix {fail_count} values in '{column}' not matching pattern → Clean & prepare → Regex replace",
        "date_not_future": f"Fix {fail_count} future dates in '{column}' → Clean & prepare → Cap dates",
        "referential_integrity": f"Fix {fail_count} orphan keys in '{column}' → Model → Validate relationships",
        "cross_column": f"Fix {fail_count} rows failing cross-column check → Clean & prepare → Calculated column",
    }
    return fixes.get(rule_type, f"Fix {fail_count} failing values")


# ── Auto-suggest rules from column semantics ──────────────────────
def suggest_rules(df: pd.DataFrame, semantics: dict | None = None) -> list[dict]:
    """Suggest quality rules based on detected column meanings."""
    rules = []
    for col in df.columns:
        col_str = str(col)
        sem = (semantics or {}).get(col_str, {})
        sem_type = sem.get("semantic_type", "")

        # Not-null for key-like columns
        if any(k in col_str.lower() for k in ("_id", "id", "key", "code")):
            rules.append({"type": "not_null", "column": col_str, "severity": "critical",
                          "name": f"{col_str} must not be null", "auto_suggested": True})
            rules.append({"type": "unique", "column": col_str, "severity": "warning",
                          "name": f"{col_str} should be unique", "auto_suggested": True})

        # Date not in future
        if sem_type in ("date", "datetime", "timestamp") or "date" in col_str.lower():
            if pd.api.types.is_datetime64_any_dtype(df[col]) or (
                df[col].dtype == "object" and pd.to_datetime(df[col].head(20), errors="coerce").notna().mean() > 0.7
            ):
                rules.append({"type": "date_not_future", "column": col_str, "severity": "warning",
                              "name": f"{col_str} dates should not be in the future", "auto_suggested": True})

        # Range for price/amount columns
        if any(k in col_str.lower() for k in ("price", "amount", "total", "revenue", "cost", "salary", "quantity", "qty")):
            if pd.api.types.is_numeric_dtype(df[col]):
                rules.append({"type": "range", "column": col_str, "severity": "warning",
                              "params": {"min": 0}, "name": f"{col_str} should be non-negative",
                              "auto_suggested": True})

        # Not-null for name/email columns
        if any(k in col_str.lower() for k in ("name", "email", "title")):
            rules.append({"type": "not_null", "column": col_str, "severity": "warning",
                          "name": f"{col_str} should not be null", "auto_suggested": True})

    return rules


def compute_quality_score(df: pd.DataFrame, rules: list[dict] | None = None,
                          ref_dfs: dict[str, pd.DataFrame] | None = None) -> dict:
    """Compute the full quality scorecard with 6 dimensions."""
    if rules is None:
        rules = suggest_rules(df)
    n = len(df)
    n_cols = df.shape[1]
    total_cells = max(n * max(n_cols, 1), 1)

    # Completeness: 1 - (missing cells / total cells)
    missing_cells = int(df.isna().sum().sum())
    completeness = 1 - missing_cells / total_cells

    # Uniqueness: 1 - (duplicate rows / total rows)
    dup_rows = int(df.duplicated().sum()) if n else 0
    uniqueness = 1 - dup_rows / n if n else 1.0

    # Evaluate all rules
    rule_results = []
    rule_failures = 0
    total_rule_checks = 0
    timeliness_score = 1.0
    accuracy_score = 1.0

    for rule in rules:
        ref_table = rule.get("params", {}).get("ref_table", "")
        ref_df = (ref_dfs or {}).get(ref_table)
        result = evaluate_rule(df, rule, ref_df)
        result["rule"] = rule
        rule_results.append(result)

        if result.get("passed") is not None:
            total_rule_checks += 1
            if not result["passed"]:
                rule_failures += 1

    # Validity: based on rule pass rate + outlier ratio
    outlier_cells = 0
    for col in df.select_dtypes(include="number").columns:
        v = df[col].dropna()
        if len(v) >= 8:
            q1, q3 = v.quantile(0.25), v.quantile(0.75)
            iqr = q3 - q1
            outlier_cells += int(((v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)).sum())
    validity = 1 - outlier_cells / total_cells

    # Consistency: check mixed types, inconsistent categories
    mixed_cols = 0
    for col in df.select_dtypes(include="object").columns:
        vals = df[col].dropna().astype(str).str.replace(",", "", regex=False).str.strip()
        if len(vals) > 0 and pd.to_numeric(vals, errors="coerce").notna().mean() > 0.8:
            mixed_cols += 1
    consistency = 1 - mixed_cols / max(n_cols, 1)

    # Timeliness: check date columns for stale data
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    if date_cols:
        now = pd.Timestamp.now()
        stale_count = 0
        for c in date_cols:
            max_date = df[c].max()
            if pd.notna(max_date) and (now - max_date).days > 365:
                stale_count += 1
        timeliness_score = 1 - stale_count / max(len(date_cols), 1)

    # Accuracy: based on rule pass rate
    if total_rule_checks > 0:
        accuracy_score = 1 - rule_failures / total_rule_checks

    # Overall score (weighted)
    overall = 100 * (
        0.25 * completeness +
        0.15 * uniqueness +
        0.20 * validity +
        0.15 * consistency +
        0.10 * timeliness_score +
        0.15 * accuracy_score
    )

    # Build issue log
    issue_log = []
    for rr in rule_results:
        if rr.get("passed") is False:
            rule = rr["rule"]
            issue_log.append({
                "severity": rule.get("severity", "warning"),
                "column": rule.get("column", ""),
                "rule_name": rule.get("name", rule["type"]),
                "rule_type": rule["type"],
                "fail_count": rr["fail_count"],
                "fail_pct": rr["fail_pct"],
                "sample_rows": rr["sample_rows"][:3],
                "suggested_fix": rr["suggested_fix"],
            })

    # Sort issues: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    issue_log.sort(key=lambda x: (severity_order.get(x["severity"], 9), -x["fail_count"]))

    return {
        "overall_score": round(overall, 1),
        "dimensions": {
            "completeness": {"score": round(completeness * 100, 1), "missing_cells": missing_cells, "total_cells": total_cells},
            "uniqueness": {"score": round(uniqueness * 100, 1), "duplicate_rows": dup_rows, "total_rows": n},
            "validity": {"score": round(validity * 100, 1), "outlier_cells": outlier_cells},
            "consistency": {"score": round(consistency * 100, 1), "mixed_type_columns": mixed_cols},
            "timeliness": {"score": round(timeliness_score * 100, 1)},
            "accuracy": {"score": round(accuracy_score * 100, 1), "rules_checked": total_rule_checks, "rules_failed": rule_failures},
        },
        "rule_results": [
            {
                "rule_name": rr["rule"].get("name", rr["rule"]["type"]),
                "rule_type": rr["rule"]["type"],
                "column": rr["rule"].get("column", ""),
                "passed": rr.get("passed"),
                "fail_count": rr["fail_count"],
                "fail_pct": rr["fail_pct"],
                "sample_rows": rr["sample_rows"][:3],
                "suggested_fix": rr["suggested_fix"],
                "error": rr.get("error"),
            }
            for rr in rule_results
        ],
        "issue_log": issue_log,
        "summary": {
            "total_rules": len(rules),
            "rules_passed": sum(1 for r in rule_results if r.get("passed") is True),
            "rules_failed": sum(1 for r in rule_results if r.get("passed") is False),
            "rules_skipped": sum(1 for r in rule_results if r.get("passed") is None),
            "critical_issues": sum(1 for i in issue_log if i["severity"] == "critical"),
            "warning_issues": sum(1 for i in issue_log if i["severity"] == "warning"),
        },
    }


# ── Rule CRUD ─────────────────────────────────────────────────────
def save_rules(owner: str, dataset_id: str, rules: list[dict]) -> list[dict]:
    """Save quality rules for a dataset."""
    saved = []
    for rule in rules:
        doc = {
            "_id": rule.get("id") or uuid.uuid4().hex[:12],
            "owner": owner,
            "dataset_id": dataset_id,
            "type": rule["type"],
            "column": rule.get("column", ""),
            "name": rule.get("name", rule["type"]),
            "severity": rule.get("severity", "warning"),
            "params": rule.get("params", {}),
            "enabled": rule.get("enabled", True),
            "auto_suggested": rule.get("auto_suggested", False),
            "created": datetime.now(timezone.utc).isoformat(),
        }
        quality_rules.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        saved.append(doc)
    return saved


def get_rules(owner: str, dataset_id: str) -> list[dict]:
    """Get all quality rules for a dataset."""
    return list(quality_rules.find({"owner": owner, "dataset_id": dataset_id}))


def delete_rule(owner: str, rule_id: str) -> None:
    quality_rules.delete_one({"_id": rule_id, "owner": owner})


# ── Report export helpers ─────────────────────────────────────────
def quality_report_html(scorecard: dict, dataset_name: str) -> str:
    """Generate an HTML quality report."""
    dims = scorecard["dimensions"]
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Data Quality Report – {dataset_name}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a2e; }}
  h1 {{ color: #16213e; border-bottom: 2px solid #0f3460; padding-bottom: .5rem; }}
  .score {{ font-size: 2.5rem; font-weight: 700; color: {'#22c55e' if scorecard['overall_score'] >= 80 else '#f59e0b' if scorecard['overall_score'] >= 60 else '#ef4444'}; }}
  .dim {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
  .dim-card {{ padding: 1rem; border-radius: .5rem; border: 1px solid #e2e8f0; text-align: center; }}
  .dim-card .val {{ font-size: 1.5rem; font-weight: 600; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ text-align: left; padding: .5rem .75rem; border-bottom: 1px solid #e2e8f0; font-size: .875rem; }}
  th {{ background: #f8fafc; font-weight: 600; }}
  .critical {{ color: #ef4444; }} .warning {{ color: #f59e0b; }} .info {{ color: #3b82f6; }}
  .pass {{ color: #22c55e; }} .fail {{ color: #ef4444; }}
</style></head><body>
<h1>📊 Data Quality Report</h1>
<p><strong>Dataset:</strong> {dataset_name} &middot; <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<div class="score">{scorecard['overall_score']}%</div>
<p>Overall Quality Score</p>

<div class="dim">"""

    for name, dim in dims.items():
        color = "#22c55e" if dim["score"] >= 80 else "#f59e0b" if dim["score"] >= 60 else "#ef4444"
        html += f'<div class="dim-card"><div class="val" style="color:{color}">{dim["score"]}%</div><div>{name.title()}</div></div>'

    html += """</div>
<h2>Issue Log</h2>
<table><tr><th>Severity</th><th>Column</th><th>Rule</th><th>Failures</th><th>Fix</th></tr>"""

    for issue in scorecard.get("issue_log", []):
        html += f"""<tr>
<td class="{issue['severity']}">{issue['severity'].upper()}</td>
<td>{issue['column']}</td><td>{issue['rule_name']}</td>
<td>{issue['fail_count']} ({issue['fail_pct']}%)</td>
<td>{issue['suggested_fix']}</td></tr>"""

    html += "</table>"

    html += """
<h2>Rule Results</h2>
<table><tr><th>Rule</th><th>Column</th><th>Result</th><th>Failures</th></tr>"""
    for rr in scorecard.get("rule_results", []):
        status = "PASS" if rr.get("passed") else "FAIL" if rr.get("passed") is False else "SKIP"
        cls = "pass" if rr.get("passed") else "fail"
        html += f'<tr><td>{rr["rule_name"]}</td><td>{rr["column"]}</td><td class="{cls}">{status}</td><td>{rr["fail_count"]}</td></tr>'

    html += "</table></body></html>"
    return html


compute_quality_scorecard = compute_quality_score
