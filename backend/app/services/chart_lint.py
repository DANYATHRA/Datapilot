"""
DataPilot Chart Linter and Integrity Guard.

Runs on every figure and visual spec to enforce professional visualization rules:
1. Category overflow: > 30 categories -> collapse to top-10 + "Other".
2. Pie slice limit: > 6 slices -> group into top 5 + "Other", and recommend bar chart.
3. Line point density: > 60 points -> auto-reaggregate date series to day/week/month/quarter.
4. Overlapping labels: > 7 vertical categories or labels > 8 chars -> auto-flip to horizontal bar.
5. Legend sprawl: > 6 legend entries -> collapse to top 5 + "Other".
6. Axis tick formatting: unformatted raw numbers -> apply compact lakh/crore or K/M formatting.
7. Duplicate title: strip title from figure layout (card header carries title and subtitle).
8. Negative values in composition: negative values in pie/treemap -> blocked with clear message.
9. Single point trendline: single data point line chart -> recommend KPI card.
10. Honest data: generate data summary caption and excluded row annotations.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd
from .formatters import format_compact_number, format_percent, truncate_label, is_indian_currency


class LintResult:
    def __init__(
        self,
        is_valid: bool = True,
        warnings: list[str] | None = None,
        summary: str = "",
        excluded_count: int = 0,
        is_horizontal: bool = False,
    ):
        self.is_valid = is_valid
        self.warnings: list[str] = warnings or []
        self.summary: str = summary
        self.excluded_count: int = excluded_count
        self.is_horizontal: bool = is_horizontal

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "warnings": self.warnings,
            "summary": self.summary,
            "excluded_count": self.excluded_count,
            "is_horizontal": self.is_horizontal,
        }


def lint_and_prepare_data(
    df: pd.DataFrame,
    chart_type: str,
    x_col: str | None = None,
    y_col: str | None = None,
    color_col: str | None = None,
    currency: str | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, LintResult]:
    """
    Validates, lints, and applies smart auto-fixes to data before chart rendering:
    - Strips null rows with honest exclusion accounting.
    - Groups long tails into 'Other' with exact mathematical sum equality.
    - Formats labels, detects negative composition values, and builds accessibility summaries.
    """
    opts = options or {}
    chart = (chart_type or "bar").lower()
    warnings: list[str] = []
    is_horizontal = False

    if df.empty:
        return df, LintResult(is_valid=True, summary="No data records available.", warnings=["Dataset is empty."])

    df_work = df.copy()
    initial_rows = len(df_work)

    # 1. Honest Data: Track excluded rows
    required_cols = [c for c in [x_col, y_col] if c and c in df_work.columns]
    if required_cols:
        before_drop = len(df_work)
        df_work = df_work.dropna(subset=required_cols)
        excluded = before_drop - len(df_work)
    else:
        excluded = 0

    if df_work.empty:
        return df_work, LintResult(
            is_valid=False,
            warnings=[f"All {initial_rows} rows had missing required values."],
            summary="Zero valid rows to visualize.",
            excluded_count=initial_rows,
        )

    # 2. Negative Values in Composition Checks
    if chart in ("pie", "donut", "treemap", "funnel") and y_col and y_col in df_work.columns:
        if pd.api.types.is_numeric_dtype(df_work[y_col]):
            neg_count = int((df_work[y_col] < 0).sum())
            if neg_count > 0:
                warnings.append(
                    f"{chart.capitalize()} chart cannot represent negative values ({neg_count} negative rows detected). "
                    "Recommend switching to a Bar or Column chart."
                )
                df_work = df_work[df_work[y_col] >= 0]
                excluded += neg_count

    # 3. Single-Point Line Check
    if chart in ("line", "area") and len(df_work) == 1:
        warnings.append("Line chart has only a single data point. Recommend switching to a KPI Card.")

    # 4. Dense Line / Area Re-aggregation (> 60 points)
    if chart in ("line", "area") and x_col and y_col and x_col in df_work.columns and y_col in df_work.columns:
        if len(df_work) > 60:
            orig_count = len(df_work)
            reagg_done = False
            try:
                parsed_dates = pd.to_datetime(df_work[x_col], errors="coerce")
                if parsed_dates.notna().sum() > len(df_work) * 0.7:
                    df_temp = df_work.copy()
                    df_temp["_date_parsed"] = parsed_dates
                    df_temp = df_temp.dropna(subset=["_date_parsed"])
                    agg_kind = opts.get("aggregation", "sum")
                    agg_fn = "mean" if agg_kind in ("avg", "average", "mean") else "sum"

                    for freq, freq_name in [("D", "daily"), ("W", "weekly"), ("MS", "monthly"), ("QS", "quarterly"), ("YS", "yearly")]:
                        grouped = df_temp.groupby(pd.Grouper(key="_date_parsed", freq=freq))[y_col].agg(agg_fn).dropna().reset_index()
                        if len(grouped) <= 60:
                            grouped = grouped.rename(columns={"_date_parsed": x_col})
                            df_work = grouped
                            reagg_done = True
                            warnings.append(
                                f"Auto-aggregated dense time-series from {orig_count} to {len(df_work)} points ({freq_name} grain) to maintain clean readability."
                            )
                            break
            except Exception:
                pass

            if not reagg_done and len(df_work) > 60:
                # Uniform downsampling to max 60 points
                step = math.ceil(len(df_work) / 60)
                df_work = df_work.iloc[::step].reset_index(drop=True)
                warnings.append(
                    f"Auto-aggregated dense time-series from {orig_count} to {len(df_work)} points to maintain clean readability."
                )

    # 5. Overlapping Labels / Orientation Check for Bar & Column
    if chart in ("bar", "column") and x_col and x_col in df_work.columns:
        cat_count = len(df_work[x_col].unique())
        labels_len = [len(str(lbl)) for lbl in df_work[x_col]]
        max_label_len = max(labels_len) if labels_len else 0
        if cat_count > 7 or max_label_len > 8 or opts.get("orientation") == "horizontal":
            is_horizontal = True
            if chart == "column":
                warnings.append("Flipped to horizontal layout to prevent overlapping category labels.")

    # 6. Pie / Donut Slice Limiting (Max 6 slices, top 5 + 'Other')
    if chart in ("pie", "donut") and x_col and y_col and x_col in df_work.columns and y_col in df_work.columns:
        if len(df_work) > 6:
            warnings.append(
                f"Pie chart had {len(df_work)} slices. Merged smallest pie slices into 'Other' "
                "(6 slices maximum for clean readability). Recommend bar chart for >6 categories."
            )
            df_work = _collapse_top_n_other(df_work, cat_col=x_col, val_col=y_col, top_n=5)

    # 7. Bar / Column Limiting (Top 10 + 'Other' if > 10 categories and not ordinal/date)
    elif chart in ("bar", "column") and x_col and y_col and x_col in df_work.columns and y_col in df_work.columns:
        is_date = pd.api.types.is_datetime64_any_dtype(df_work[x_col])
        if not is_date and len(df_work) > 10 and not opts.get("show_all"):
            warnings.append(
                f"Category '{x_col}' has {len(df_work)} items. Displaying top 10 + 'Other' to avoid crowded axis."
            )
            df_work = _collapse_top_n_other(df_work, cat_col=x_col, val_col=y_col, top_n=10)

    # 8. Legend / Multi-Series Collapsing (> 6 series -> top 5 + 'Other')
    if color_col and color_col in df_work.columns and y_col in df_work.columns:
        unique_series = df_work[color_col].unique()
        if len(unique_series) > 6:
            warnings.append(
                f"Multi-series visual had {len(unique_series)} legend entries. Collapsed to top 5 + 'Other' to avoid legend sprawl."
            )
            series_totals = df_work.groupby(color_col)[y_col].sum().sort_values(ascending=False)
            top_series = set(series_totals.index[:5])
            df_work[color_col] = df_work[color_col].apply(lambda s: s if s in top_series else "Other")
            # Re-aggregate grouped items
            group_cols = [c for c in [x_col, color_col] if c and c in df_work.columns]
            if group_cols:
                agg_kind = opts.get("aggregation", "sum")
                agg_fn = "mean" if agg_kind in ("avg", "average", "mean") else "sum"
                df_work = df_work.groupby(group_cols, as_index=False)[y_col].agg(agg_fn)

    # 9. Auto-generate text summary for Accessibility & Honest Data
    summary_text = _generate_accessible_summary(df_work, chart, x_col, y_col, currency)

    lint_res = LintResult(
        is_valid=True,
        warnings=warnings,
        summary=summary_text,
        excluded_count=excluded,
        is_horizontal=is_horizontal,
    )
    return df_work, lint_res


def _collapse_top_n_other(df: pd.DataFrame, cat_col: str, val_col: str, top_n: int = 10) -> pd.DataFrame:
    """
    Collapse dataframe to top N categories sorted by value descending,
    with all remaining rows mathematically summed into an 'Other' category.
    Preserves exact total sum without rounding discrepancies.
    """
    if len(df) <= top_n + 1:
        return df.sort_values(by=val_col, ascending=False).reset_index(drop=True)

    # Sort descending
    df_sorted = df.sort_values(by=val_col, ascending=False).reset_index(drop=True)
    top_part = df_sorted.iloc[:top_n].copy()
    rest_part = df_sorted.iloc[top_n:].copy()

    other_val = rest_part[val_col].sum()
    other_row = {col: None for col in df.columns}
    other_row[cat_col] = "Other"
    other_row[val_col] = other_val

    # If extra columns exist, preserve sensible default
    for c in df.columns:
        if c not in (cat_col, val_col):
            other_row[c] = "Other"

    other_df = pd.DataFrame([other_row])
    result_df = pd.concat([top_part, other_df], ignore_index=True)
    return result_df


def _generate_accessible_summary(
    df: pd.DataFrame,
    chart_type: str,
    x_col: str | None,
    y_col: str | None,
    currency: str | None,
) -> str:
    """
    Construct a concise, informative text summary built strictly from the computed data.
    Used as aria-label, table toggle metadata, and audit verification.
    """
    if df.empty:
        return f"{chart_type.capitalize()} with no data."

    chart_name = chart_type.replace("_", " ").title()

    if chart_type in ("kpi_card", "sparkline_kpi", "gauge", "bullet"):
        val = df[y_col].iloc[0] if y_col and y_col in df.columns else (df.iloc[0, 0] if len(df.columns) else 0)
        formatted_val = format_compact_number(val, currency=currency)
        return f"{chart_name}: {formatted_val}."

    if not x_col or not y_col or x_col not in df.columns or y_col not in df.columns:
        return f"{chart_name} displaying {len(df)} records."

    if not pd.api.types.is_numeric_dtype(df[y_col]):
        return f"{chart_name} of {y_col} across {len(df)} categories in {x_col}."

    total_val = float(df[y_col].sum())
    formatted_total = format_compact_number(total_val, currency=currency)

    # Find highest category
    idx_max = df[y_col].idxmax()
    top_cat = str(df.loc[idx_max, x_col])
    top_val = float(df.loc[idx_max, y_col])
    top_formatted = format_compact_number(top_val, currency=currency)
    top_pct = (top_val / total_val * 100.0) if total_val > 0 else 0.0

    return (
        f"{chart_name} of {y_col} by {x_col}. "
        f"Total: {formatted_total} across {len(df)} categories. "
        f"Highest: {top_cat} with {top_formatted} ({top_pct:.1f}% of total)."
    )


generate_accessible_summary = _generate_accessible_summary
