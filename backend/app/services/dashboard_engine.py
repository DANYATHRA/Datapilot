"""
Dashboard Engine & Shared Calculation Layer for DataPilot (Power BI / Tableau Inspired).

Single source of truth for:
1. Applied Filters Execution (date range, up to 3 categorical slicers, and cross-filter)
2. Auto-Detected Slicer Options (date range + up to 3 categories with item counts)
3. KPI Calculations (up to 6 business metrics by semantic meaning)
4. Suitable Charts Recommender (cap 12, strictly guarded by column requirements and grouped by section)
   - Proper humanized names, axes with units, zero-baseline, readable ticks
   - Horizontal bars when categories > 6
   - Stable 6-color palette + slate grey
   - Data labels on bars <= 12 and pie slices
   - Aggregated table data attached to each chart for "Show as table" and "Export CSV"
   - Date drill-down (Year -> Quarter -> Month -> Day)
   - Full visual suite: KPI, Clustered/Stacked column & bar, Line, Area, Combo (bar+line),
     Pie/Donut, Treemap, Scatter, Histogram, Box plot, Heatmap, Likert stacked bar
5. Consolidated Key Insights (5-8 plain sentences with exact numbers)
6. Executive PDF Report Generation (ReportLab)
"""
from __future__ import annotations

import io
import math
import re
from datetime import datetime
from typing import Any
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import stats

from .column_semantics import infer_column_semantic_type


# ─────────────────────────────────────────────────────────────────────────────
# PALETTE & PLOTLY THEME
# ─────────────────────────────────────────────────────────────────────────────
TEAL_PRIMARY = "#0B7A75"
BRAND_PALETTE_6 = [
    "#0B7A75",  # Primary Teal
    "#2563EB",  # Royal Blue
    "#D97706",  # Warm Amber
    "#7C3AED",  # Purple
    "#059669",  # Emerald Green
    "#DC2626",  # Coral Red
]
COLOR_OTHER = "#94A3B8"  # Slate grey for 7th+ category

PLOTLY_LAYOUT_DEFAULTS = {
    "font": {"family": "Inter, system-ui, sans-serif", "size": 12, "color": "#101828"},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "margin": {"l": 50, "r": 20, "t": 36, "b": 44},
    "hovermode": "closest",
    "xaxis": {
        "gridcolor": "#F2F4F7",
        "linecolor": "#E4E7EC",
        "tickfont": {"size": 11, "color": "#475467"},
        "showgrid": False,
    },
    "yaxis": {
        "gridcolor": "#F2F4F7",
        "linecolor": "#E4E7EC",
        "tickfont": {"size": 11, "color": "#475467"},
        "showgrid": True,
        "zeroline": True,
        "zerolinecolor": "#E4E7EC",
        "rangemode": "tozero",
    },
}

ACRONYMS = {"id", "pan", "gst", "sku", "dob", "pii", "aov", "kpi", "nps", "url", "inr", "usd", "eur"}
WORD_MAP = {
    "qty": "Quantity",
    "amt": "Amount",
    "cust": "Customer",
    "prod": "Product",
    "cat": "Category",
    "desc": "Description",
    "val": "Value",
    "num": "Number",
    "no": "Number",
    "pct": "Percent",
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS: HUMANIZATION, MEASURE NAMES, STABLE COLORS
# ─────────────────────────────────────────────────────────────────────────────
def humanize_name(col_name: str) -> str:
    """Humanize column name while preserving uppercase acronyms (ID, GST, SKU, PAN)."""
    if not col_name:
        return ""
    parts = re.split(r"[_\s]+", str(col_name).strip())
    res = []
    for p in parts:
        p_lower = p.lower()
        if p_lower in ACRONYMS:
            res.append(p_lower.upper())
        elif p_lower in WORD_MAP:
            res.append(WORD_MAP[p_lower])
        else:
            res.append(p.capitalize())
    return " ".join(res)


def get_measure_label(col_name: str, agg: str = "sum") -> str:
    """Standard measure name stating explicit aggregation: 'Total Revenue', 'Order Count', etc."""
    h = humanize_name(col_name)
    agg_lower = agg.lower()
    if agg_lower == "sum":
        if any(w in col_name.lower() for w in ("revenue", "sales", "amount", "spend", "cost", "turnover")):
            return f"Total {h}"
        elif any(w in col_name.lower() for w in ("qty", "quantity", "volume", "unit", "items")):
            return f"Total {h}"
        return f"Total {h}"
    elif agg_lower in ("mean", "avg"):
        return f"Average {h}"
    elif agg_lower in ("distinct", "unique"):
        return f"Distinct {h}"
    elif agg_lower == "count":
        return f"{h} Count"
    return f"{h} ({agg.capitalize()})"


def get_stable_colors(categories: list[str]) -> list[str]:
    """Assign stable colors: up to 6 distinct palette colors + grey for the rest."""
    colors = []
    for i in range(len(categories)):
        if i < len(BRAND_PALETTE_6):
            colors.append(BRAND_PALETTE_6[i])
        else:
            colors.append(COLOR_OTHER)
    return colors


def _format_currency(val: float, symbol: str = "₹") -> str:
    if val is None or not np.isfinite(val):
        return "-"
    abs_v = abs(val)
    sign = "-" if val < 0 else ""
    if symbol == "₹":
        if abs_v >= 10_000_000:
            return f"{sign}₹{abs_v / 10_000_000:.2f} Cr"
        elif abs_v >= 100_000:
            return f"{sign}₹{abs_v / 100_000:.2f} L"
        else:
            return f"{sign}₹{abs_v:,.0f}"
    else:
        if abs_v >= 1_000_000_000:
            return f"{sign}{symbol}{abs_v / 1_000_000_000:.2f}B"
        elif abs_v >= 1_000_000:
            return f"{sign}{symbol}{abs_v / 1_000_000:.2f}M"
        elif abs_v >= 1_000:
            return f"{sign}{symbol}{abs_v / 1_000:.1f}k"
        else:
            return f"{sign}{symbol}{abs_v:,.0f}"


def _format_compact_num(val: float) -> str:
    if val is None or not np.isfinite(val):
        return "-"
    abs_v = abs(val)
    sign = "-" if val < 0 else ""
    if abs_v >= 1_000_000:
        return f"{sign}{abs_v / 1_000_000:.1f}M"
    elif abs_v >= 1_000:
        return f"{sign}{abs_v / 1_000:.1f}k"
    elif abs_v == int(abs_v):
        return f"{sign}{int(abs_v):,}"
    else:
        return f"{sign}{abs_v:.2f}"


def clean_and_prepare_df_types(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Safely cast strings to numbers/dates where appropriate without data loss."""
    df = df_raw.copy()
    for col in df.columns:
        s = df[col]
        col_lower = str(col).lower()
        # Dates
        if any(w in col_lower for w in ("date", "time", "dob", "period", "timestamp")) and not pd.api.types.is_datetime64_any_dtype(s):
            try:
                converted = pd.to_datetime(s, format="mixed", errors="coerce")
                if converted.notna().sum() >= max(2, len(s) * 0.4):
                    df[col] = converted
                    continue
            except Exception:
                pass

        # Numeric / Currency
        if not pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_datetime64_any_dtype(s):
            cleaned_s = s.astype(str).str.replace(r"[₹$,€£ ]", "", regex=True)
            num_s = pd.to_numeric(cleaned_s, errors="coerce")
            if num_s.notna().sum() >= max(2, len(s) * 0.6) and not any(w in col_lower for w in ("id", "code", "phone", "pin", "roll")):
                df[col] = num_s

    return df


def make_table_data(x_label: str, y_label: str, x_vals: list[Any], y_vals: list[float], unit: str = "") -> dict[str, Any]:
    """Generate structured table data with totals and conditional data bar percentages."""
    total_val = sum(y_vals) if y_vals else 0
    max_val = max(y_vals) if y_vals else 1
    rows = []
    for x, y in zip(x_vals, y_vals):
        pct = (y / total_val * 100) if total_val > 0 else 0
        pct_of_max = (y / max_val * 100) if max_val > 0 else 0
        formatted_val = f"{unit}{y:,.2f}" if unit else f"{y:,.2f}"
        rows.append({
            "category": str(x),
            "value": y,
            "formatted_value": formatted_val,
            "percent_of_total": f"{pct:.1f}%",
            "percent_of_max": round(pct_of_max, 1),
        })
    return {
        "columns": [
            {"key": "category", "label": x_label},
            {"key": "formatted_value", "label": y_label},
            {"key": "percent_of_total", "label": "% of Total"},
        ],
        "rows": rows,
        "total": {
            "category": "Total",
            "formatted_value": f"{unit}{total_val:,.2f}" if unit else f"{total_val:,.2f}",
            "percent_of_total": "100.0%",
            "value": total_val,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. APPLY FILTERS (SLICERS & CROSS-FILTERING)
# ─────────────────────────────────────────────────────────────────────────────
def apply_filters_to_df(df: pd.DataFrame, filters: dict[str, Any] | None) -> pd.DataFrame:
    if not filters:
        return df

    filtered = df.copy()

    # 1. Date range
    date_col = filters.get("date_col")
    date_min = filters.get("date_min")
    date_max = filters.get("date_max")

    if date_col and date_col in filtered.columns and pd.api.types.is_datetime64_any_dtype(filtered[date_col]):
        if date_min:
            try:
                min_ts = pd.to_datetime(date_min)
                filtered = filtered[filtered[date_col] >= min_ts]
            except Exception:
                pass
        if date_max:
            try:
                max_ts = pd.to_datetime(date_max)
                filtered = filtered[filtered[date_col] <= max_ts]
            except Exception:
                pass

    # 2. Categorical filters (slicers)
    cat_filters = filters.get("categories") or {}
    for col_name, selected_values in cat_filters.items():
        if col_name in filtered.columns and selected_values and isinstance(selected_values, list):
            filtered = filtered[filtered[col_name].astype(str).isin([str(v) for v in selected_values])]

    # 3. Cross-filter (single or multi point cross-filtering)
    cross_dim = filters.get("cross_dim")
    cross_val = filters.get("cross_val")
    if cross_dim and cross_val and cross_dim in filtered.columns:
        if isinstance(cross_val, list):
            filtered = filtered[filtered[cross_dim].astype(str).isin([str(v) for v in cross_val])]
        else:
            filtered = filtered[filtered[cross_dim].astype(str) == str(cross_val)]

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
# 2. AUTO-DETECT SLICERS
# ─────────────────────────────────────────────────────────────────────────────
def detect_available_filters(df: pd.DataFrame) -> dict[str, Any]:
    """Returns slicer options: 1 date range + up to 3 searchable categories with item counts."""
    out: dict[str, Any] = {
        "date_filter": None,
        "category_filters": [],
    }

    # 1. Date column
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c]) and df[c].notna().any()]
    if date_cols:
        dcol = date_cols[0]
        s_date = df[dcol].dropna()
        out["date_filter"] = {
            "column": dcol,
            "min": s_date.min().strftime("%Y-%m-%d"),
            "max": s_date.max().strftime("%Y-%m-%d"),
            "label": humanize_name(dcol),
        }

    # 2. Top 3 categorical columns by distinct count (between 2 and 25 categories)
    cat_candidates = []
    for c in df.columns:
        if c in date_cols:
            continue
        col_lower = str(c).lower()
        if any(w in col_lower for w in ("id", "email", "phone", "name", "address", "url")):
            continue
        s = df[c].dropna()
        n_unique = s.nunique()
        if 2 <= n_unique <= 25:
            counts = s.value_counts()
            options = [
                {"value": str(val), "label": str(val), "count": int(cnt)}
                for val, cnt in counts.items()
            ]
            options.sort(key=lambda x: x["value"])
            top_share = counts.iloc[0] / len(s) if len(s) > 0 else 1
            score = n_unique * (1 - top_share)
            cat_candidates.append({
                "column": c,
                "label": humanize_name(c),
                "options": options,
                "score": score,
            })

    cat_candidates.sort(key=lambda x: x["score"], reverse=True)
    out["category_filters"] = [
        {"column": c["column"], "label": c["label"], "options": c["options"]}
        for c in cat_candidates[:3]
    ]

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. COMPUTE KPIS (UP TO 6)
# ─────────────────────────────────────────────────────────────────────────────
def compute_kpis(df: pd.DataFrame, source_meta: dict | None = None) -> list[dict[str, Any]]:
    kpis = []
    if len(df) == 0:
        return [
            {"id": "kpi_total_records", "label": "Records", "value": "0", "delta": None, "subtext": "Filtered records"}
        ]

    currency_sym = "₹"
    currencies = (source_meta or {}).get("column_currencies", {})
    if currencies:
        currency_sym = next(iter(currencies.values()), "₹")

    num_cols = [c for c in df.select_dtypes("number").columns if not any(w in c.lower() for w in ("id", "phone", "pin", "roll"))]
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    date_col = date_cols[0] if date_cols else None

    def calc_period_delta(measure_col: str, agg: str = "sum") -> float | None:
        if not date_col or len(df) < 6:
            return None
        sorted_df = df.dropna(subset=[date_col, measure_col]).sort_values(date_col)
        if len(sorted_df) < 4:
            return None
        mid = len(sorted_df) // 2
        p1 = sorted_df.iloc[:mid][measure_col]
        p2 = sorted_df.iloc[mid:][measure_col]
        v1 = p1.sum() if agg == "sum" else p1.mean()
        v2 = p2.sum() if agg == "sum" else p2.mean()
        if v1 and np.isfinite(v1) and v1 > 0:
            return round(((v2 - v1) / v1) * 100, 1)
        return None

    # 1. Total Revenue / Sales
    money_col = None
    for kw in ("revenue", "sales", "total_amount", "amount", "price"):
        m_col = next((c for c in num_cols if kw in c.lower()), None)
        if m_col:
            money_col = m_col
            break
    if money_col:
        tot = float(df[money_col].sum())
        delta = calc_period_delta(money_col, "sum")
        kpis.append({
            "id": "kpi_total_revenue",
            "label": get_measure_label(money_col, "sum"),
            "value": _format_currency(tot, currency_sym),
            "raw_value": tot,
            "delta": delta,
            "is_positive": delta > 0 if delta is not None else None,
            "subtext": "vs prior period" if delta is not None else "Total value",
        })

    # 2. Total Quantity / Volume
    qty_col = next((c for c in num_cols if any(w in c.lower() for w in ("unit", "qty", "quantity", "volume", "count", "items")) and c != money_col), None)
    if qty_col:
        tot_qty = float(df[qty_col].sum())
        delta = calc_period_delta(qty_col, "sum")
        kpis.append({
            "id": "kpi_total_units",
            "label": get_measure_label(qty_col, "sum"),
            "value": _format_compact_num(tot_qty),
            "raw_value": tot_qty,
            "delta": delta,
            "is_positive": delta > 0 if delta is not None else None,
            "subtext": "vs prior period" if delta is not None else "Total units",
        })

    # 3. Order / Record Volume
    order_id_col = next((c for c in df.columns if any(w in c.lower() for w in ("order_id", "order_no", "invoice", "record_id"))), None)
    total_orders = df[order_id_col].nunique() if order_id_col else len(df)
    kpis.append({
        "id": "kpi_total_orders",
        "label": "Order Count" if order_id_col else "Record Count",
        "value": f"{total_orders:,}",
        "raw_value": total_orders,
        "delta": None,
        "subtext": "Unique records",
    })

    # 4. Average Order Value
    if money_col and len(df) > 0:
        aov = float(df[money_col].mean())
        delta = calc_period_delta(money_col, "mean")
        kpis.append({
            "id": "kpi_avg_order_value",
            "label": f"Average {humanize_name(money_col)}",
            "value": _format_currency(aov, currency_sym),
            "raw_value": aov,
            "delta": delta,
            "is_positive": delta > 0 if delta is not None else None,
            "subtext": "Per transaction",
        })

    # 5. Distinct Customers / Users
    cust_col = next((c for c in df.columns if any(w in c.lower() for w in ("customer", "client", "user", "student", "buyer"))), None)
    if cust_col and cust_col != order_id_col:
        n_cust = int(df[cust_col].nunique())
        kpis.append({
            "id": "kpi_total_customers",
            "label": f"Distinct {humanize_name(cust_col)}s",
            "value": _format_compact_num(n_cust),
            "raw_value": n_cust,
            "delta": None,
            "subtext": "Active accounts",
        })

    # 6. Average Rating
    rating_col = next((c for c in num_cols if any(w in c.lower() for w in ("rating", "satisfaction", "score", "nps", "review"))), None)
    if rating_col:
        avg_rating = float(df[rating_col].mean())
        kpis.append({
            "id": "kpi_avg_rating",
            "label": f"Average {humanize_name(rating_col)}",
            "value": f"{avg_rating:.2f} / 5",
            "raw_value": avg_rating,
            "delta": None,
            "subtext": "Average score",
        })

    return kpis[:6]


# ─────────────────────────────────────────────────────────────────────────────
# 4. SUITABLE CHARTS RECOMMENDER (POWER BI / TABLEAU SUITE)
# ─────────────────────────────────────────────────────────────────────────────
def build_suitable_charts(
    df: pd.DataFrame,
    source_meta: dict | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    charts = []
    if len(df) < 2:
        return charts

    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c]) and df[c].notna().any()]
    date_col = date_cols[0] if date_cols else None

    num_cols = [
        c for c in df.select_dtypes("number").columns
        if not any(w in c.lower() for w in ("id", "phone", "pin", "roll")) and df[c].nunique() > 1
    ]

    cat_cols = []
    for c in df.columns:
        if c in date_cols or c in num_cols:
            continue
        col_lower = str(c).lower()
        if any(w in col_lower for w in ("id", "email", "phone", "url", "address")):
            continue
        nu = df[c].nunique()
        if 2 <= nu <= 25:
            cat_cols.append(c)

    primary_measure = next((c for c in num_cols if any(w in c.lower() for w in ("revenue", "sales", "amount"))), num_cols[0] if num_cols else None)
    secondary_measure = next((c for c in num_cols if c != primary_measure), None)

    currency_sym = (source_meta or {}).get("column_currencies", {}).get(primary_measure or "", "₹")
    p_label = get_measure_label(primary_measure, "sum") if primary_measure else "Measure"
    s_label = get_measure_label(secondary_measure, "sum") if secondary_measure else ""

    date_grain = (filters or {}).get("date_grain", "month").lower()

    # ── A. TRENDS (Line / Area / Combo) ───────────────────────────────────────
    if date_col and primary_measure:
        date_s = df[date_col].dropna()
        span_days = (date_s.max() - date_s.min()).days if len(date_s) > 0 else 0

        # Resample based on grain or auto-grain
        if date_grain == "year" or span_days > 365 * 3:
            freq, strf, grain_name = "YS", "%Y", "Year"
        elif date_grain == "quarter":
            freq, strf, grain_name = "QS", "Q", "Quarter"
        elif date_grain == "day" or (date_grain != "year" and span_days <= 45):
            freq, strf, grain_name = "D", "%d %b %Y", "Day"
        else:
            freq, strf, grain_name = "MS", "%b %Y", "Month"

        trend_df = (
            df.dropna(subset=[date_col, primary_measure])
            .set_index(date_col)[primary_measure]
            .resample(freq)
            .sum()
            .reset_index()
        )

        if len(trend_df) >= 2:
            if grain_name == "Quarter":
                x_vals = [f"Q{ts.quarter} {ts.year}" for ts in trend_df[date_col]]
            else:
                x_vals = trend_df[date_col].dt.strftime(strf).tolist()
            y_vals = [round(float(v), 2) for v in trend_df[primary_measure]]

            # 1. Line Chart
            fig_line = go.Figure()
            fig_line.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="lines+markers",
                line={"color": TEAL_PRIMARY, "width": 2.5},
                marker={"size": 6, "color": TEAL_PRIMARY},
                fill="tozeroy",
                fillcolor="rgba(11, 122, 117, 0.08)",
                name=p_label,
                hovertemplate="%{x}<br><b>" + currency_sym + "%{y:,.2f}</b><extra></extra>",
            ))
            layout_line = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_line["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=f"{p_label} ({currency_sym})")
            layout_line["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=f"{humanize_name(date_col)} ({grain_name})")
            fig_line.update_layout(**layout_line)

            table_trend = make_table_data(grain_name, p_label, x_vals, y_vals, currency_sym)

            charts.append({
                "id": "chart_trend_primary",
                "title": f"{p_label} by {grain_name}",
                "section": "Trends",
                "chart_type": "line",
                "compatible_types": ["line", "area", "column"],
                "figure": fig_line.to_plotly_json(),
                "fields": {"x": date_col, "y": primary_measure, "aggregation": "sum"},
                "date_drill": {"grain": grain_name.lower(), "column": date_col},
                "x_vals": x_vals,
                "y_vals": y_vals,
                "table_data": table_trend,
            })

            # 2. Combo Chart (Bars + Line) if secondary measure exists
            if secondary_measure:
                trend_sec = (
                    df.dropna(subset=[date_col, secondary_measure])
                    .set_index(date_col)[secondary_measure]
                    .resample(freq)
                    .sum()
                    .reset_index()
                )
                if len(trend_sec) == len(trend_df):
                    y2_vals = [round(float(v), 2) for v in trend_sec[secondary_measure]]
                    fig_combo = go.Figure()
                    fig_combo.add_trace(go.Bar(
                        x=x_vals,
                        y=y_vals,
                        name=p_label,
                        marker_color=TEAL_PRIMARY,
                        hovertemplate="%{x}<br>" + p_label + ": <b>" + currency_sym + "%{y:,.2f}</b><extra></extra>",
                    ))
                    fig_combo.add_trace(go.Scatter(
                        x=x_vals,
                        y=y2_vals,
                        name=s_label,
                        mode="lines+markers",
                        line={"color": "#D97706", "width": 2.5},
                        marker={"size": 6, "color": "#D97706"},
                        yaxis="y2",
                        hovertemplate="%{x}<br>" + s_label + ": <b>%{y:,.0f}</b><extra></extra>",
                    ))
                    layout_combo = dict(PLOTLY_LAYOUT_DEFAULTS)
                    layout_combo["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=f"{p_label} ({currency_sym})")
                    layout_combo["yaxis2"] = {
                        "title": s_label,
                        "overlaying": "y",
                        "side": "right",
                        "showgrid": False,
                        "zeroline": False,
                        "rangemode": "tozero",
                        "tickfont": {"size": 11, "color": "#D97706"},
                    }
                    layout_combo["legend"] = {"orientation": "h", "y": -0.2}
                    fig_combo.update_layout(**layout_combo)

                    charts.append({
                        "id": "chart_combo_trends",
                        "title": f"{p_label} and {s_label} over Time",
                        "section": "Trends",
                        "chart_type": "combo",
                        "compatible_types": ["combo", "line", "column"],
                        "figure": fig_combo.to_plotly_json(),
                        "fields": {"x": date_col, "y": primary_measure, "y2": secondary_measure, "aggregation": "sum"},
                        "date_drill": {"grain": grain_name.lower(), "column": date_col},
                        "x_vals": x_vals,
                        "y_vals": y_vals,
                        "table_data": table_trend,
                    })

    # ── B. BREAKDOWNS (Column / Horizontal Bar / Pie / Treemap / Heatmap) ───
    for cat in cat_cols[:3]:
        if not primary_measure:
            break
        agg_df = (
            df.dropna(subset=[cat, primary_measure])
            .groupby(cat)[primary_measure]
            .sum()
            .reset_index()
            .sort_values(primary_measure, ascending=False)
        )
        if len(agg_df) < 2:
            continue

        cats = agg_df[cat].astype(str).tolist()
        vals = [round(float(v), 2) for v in agg_df[primary_measure]]
        stable_colors = get_stable_colors(cats)
        c_label = humanize_name(cat)
        tot_b = sum(vals) if vals else 1

        # Orientation Rule: auto-switch to horizontal bars when category labels > 6
        is_horizontal = len(cats) > 6

        fig_bar = go.Figure()
        if is_horizontal:
            # Sorted ascending so highest is at the top of horizontal chart
            cats_h = list(reversed(cats))
            vals_h = list(reversed(vals))
            colors_h = list(reversed(stable_colors))
            fig_bar.add_trace(go.Bar(
                x=vals_h,
                y=cats_h,
                orientation="h",
                marker_color=colors_h,
                text=[f"{v:,.0f}" if len(cats) <= 12 else "" for v in vals_h],
                textposition="outside",
                hovertemplate="%{y}<br><b>" + currency_sym + "%{x:,.2f}</b><extra></extra>",
            ))
            layout_bar = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_bar["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=f"{p_label} ({currency_sym})")
            layout_bar["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=c_label)
        else:
            fig_bar.add_trace(go.Bar(
                x=cats,
                y=vals,
                orientation="v",
                marker_color=stable_colors,
                text=[f"{v:,.0f}" if len(cats) <= 12 else "" for v in vals],
                textposition="outside",
                hovertemplate="%{x}<br><b>" + currency_sym + "%{y:,.2f}</b><extra></extra>",
            ))
            layout_bar = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_bar["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=f"{p_label} ({currency_sym})")
            layout_bar["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=c_label)

        fig_bar.update_layout(**layout_bar)
        table_bar = make_table_data(c_label, p_label, cats, vals, currency_sym)

        charts.append({
            "id": f"chart_breakdown_{cat}",
            "title": f"{p_label} by {c_label}",
            "section": "Breakdowns",
            "chart_type": "bar" if is_horizontal else "column",
            "compatible_types": ["column", "bar", "donut"] if len(cats) <= 6 else ["bar", "column", "treemap"],
            "figure": fig_bar.to_plotly_json(),
            "fields": {"x": cat, "y": primary_measure, "aggregation": "sum"},
            "x_vals": cats,
            "y_vals": vals,
            "table_data": table_bar,
        })

        # Donut/Pie: ONLY if categories <= 6
        if 2 <= len(cats) <= 6:
            fig_pie = go.Figure()
            fig_pie.add_trace(go.Pie(
                labels=cats,
                values=vals,
                hole=0.55,
                marker={"colors": stable_colors},
                textinfo="label+percent",
                hoverinfo="label+value+percent",
            ))
            pie_layout = dict(PLOTLY_LAYOUT_DEFAULTS)
            pie_layout["showlegend"] = True
            pie_layout["legend"] = {"title": {"text": c_label}}
            fig_pie.update_layout(**pie_layout)

            charts.append({
                "id": f"chart_donut_{cat}",
                "title": f"Share of {p_label} by {c_label}",
                "section": "Breakdowns",
                "chart_type": "donut",
                "compatible_types": ["donut", "pie", "bar"],
                "figure": fig_pie.to_plotly_json(),
                "fields": {"x": cat, "y": primary_measure, "aggregation": "sum"},
                "x_vals": cats,
                "y_vals": vals,
                "table_data": table_bar,
            })

    # Treemap (if at least 1 category with > 4 items)
    if cat_cols and primary_measure:
        t_cat = cat_cols[0]
        agg_tree = df.dropna(subset=[t_cat, primary_measure]).groupby(t_cat)[primary_measure].sum().reset_index()
        if len(agg_tree) >= 3:
            t_cats = agg_tree[t_cat].astype(str).tolist()
            t_vals = [round(float(v), 2) for v in agg_tree[primary_measure]]
            fig_tree = go.Figure(go.Treemap(
                labels=t_cats,
                parents=[""] * len(t_cats),
                values=t_vals,
                textinfo="label+value+percent root",
                marker_colors=get_stable_colors(t_cats),
                hovertemplate="<b>%{label}</b><br>" + p_label + ": " + currency_sym + "%{value:,.0f}<extra></extra>",
            ))
            fig_tree.update_layout(**PLOTLY_LAYOUT_DEFAULTS)
            charts.append({
                "id": "chart_treemap_breakdown",
                "title": f"{p_label} Treemap by {humanize_name(t_cat)}",
                "section": "Breakdowns",
                "chart_type": "treemap",
                "compatible_types": ["treemap", "bar"],
                "figure": fig_tree.to_plotly_json(),
                "fields": {"x": t_cat, "y": primary_measure, "aggregation": "sum"},
                "x_vals": t_cats,
                "y_vals": t_vals,
                "table_data": make_table_data(humanize_name(t_cat), p_label, t_cats, t_vals, currency_sym),
            })

    # Heatmap (Cross-tabulation if 2 categorical columns exist)
    if len(cat_cols) >= 2 and primary_measure:
        c1, c2 = cat_cols[0], cat_cols[1]
        piv = df.pivot_table(index=c1, columns=c2, values=primary_measure, aggfunc="sum", fill_value=0)
        if 2 <= piv.shape[0] <= 8 and 2 <= piv.shape[1] <= 8:
            fig_hm = go.Figure(go.Heatmap(
                z=piv.values.round(1).tolist(),
                x=[str(c) for c in piv.columns],
                y=[str(r) for r in piv.index],
                colorscale="Blues",
                hovertemplate=f"{humanize_name(c2)}: %{{x}}<br>{humanize_name(c1)}: %{{y}}<br>{p_label}: " + currency_sym + "%{z:,.0f}<extra></extra>",
            ))
            hm_layout = dict(PLOTLY_LAYOUT_DEFAULTS)
            hm_layout["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=humanize_name(c2))
            hm_layout["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=humanize_name(c1))
            fig_hm.update_layout(**hm_layout)
            charts.append({
                "id": "chart_heatmap_breakdown",
                "title": f"{p_label} Heatmap: {humanize_name(c1)} vs {humanize_name(c2)}",
                "section": "Breakdowns",
                "chart_type": "heatmap",
                "compatible_types": ["heatmap"],
                "figure": fig_hm.to_plotly_json(),
                "fields": {"x": c2, "y": c1, "z": primary_measure, "aggregation": "sum"},
            })

    # ── C. DISTRIBUTIONS (Histogram / Box / Scatter) ──────────────────────────
    for col in num_cols[:2]:
        s_clean = df[col].dropna()
        if len(s_clean) >= 10:
            h_col = humanize_name(col)
            # Histogram
            fig_hist = go.Figure()
            fig_hist.add_trace(go.Histogram(
                x=s_clean.tolist(),
                marker_color=TEAL_PRIMARY,
                opacity=0.85,
                hovertemplate="Range: %{x}<br>Count: %{y}<extra></extra>",
            ))
            layout_hist = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_hist["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=h_col)
            layout_hist["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title="Frequency (Count)")
            fig_hist.update_layout(**layout_hist)

            charts.append({
                "id": f"chart_dist_{col}",
                "title": f"Distribution of {h_col}",
                "section": "Distributions",
                "chart_type": "histogram",
                "compatible_types": ["histogram", "box"],
                "figure": fig_hist.to_plotly_json(),
                "fields": {"x": col, "y": None, "aggregation": "count"},
            })

            # Box Plot
            fig_box = go.Figure()
            fig_box.add_trace(go.Box(
                y=s_clean.tolist(),
                name=h_col,
                marker_color=TEAL_PRIMARY,
                boxpoints="outliers",
                hovertemplate="%{y:,.2f}<extra></extra>",
            ))
            layout_box = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_box["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=h_col)
            fig_box.update_layout(**layout_box)

            charts.append({
                "id": f"chart_box_{col}",
                "title": f"Quartiles and Outliers for {h_col}",
                "section": "Distributions",
                "chart_type": "box",
                "compatible_types": ["box", "histogram"],
                "figure": fig_box.to_plotly_json(),
                "fields": {"x": None, "y": col, "aggregation": "distribution"},
            })

    # Scatter: ONLY if 2 numeric columns exist
    if primary_measure and secondary_measure and len(df) >= 10:
        scatter_sub = df.dropna(subset=[primary_measure, secondary_measure])
        fig_scatter = go.Figure()
        fig_scatter.add_trace(go.Scatter(
            x=scatter_sub[secondary_measure].tolist(),
            y=scatter_sub[primary_measure].tolist(),
            mode="markers",
            marker={"size": 7, "color": TEAL_PRIMARY, "opacity": 0.75},
            hovertemplate=f"{s_label}: %{{x}}<br>{p_label}: %{{y}}<extra></extra>",
        ))
        layout_scat = dict(PLOTLY_LAYOUT_DEFAULTS)
        layout_scat["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=s_label)
        layout_scat["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=f"{p_label} ({currency_sym})")
        fig_scatter.update_layout(**layout_scat)

        charts.append({
            "id": "chart_rel_scatter",
            "title": f"{p_label} vs {s_label}",
            "section": "Distributions",
            "chart_type": "scatter",
            "compatible_types": ["scatter"],
            "fields": {"x": secondary_measure, "y": primary_measure, "aggregation": "none"},
            "figure": fig_scatter.to_plotly_json(),
        })

    # ── D. RATINGS (Likert Stacked Bar / Average Rating Bar) ─────────────────
    rating_cols = [c for c in num_cols if any(w in c.lower() for w in ("rating", "score", "satisfaction", "recommend", "nps"))]
    if rating_cols and cat_cols:
        r_col = rating_cols[0]
        c_col = cat_cols[0]
        r_h = humanize_name(r_col)
        c_h = humanize_name(c_col)

        # 1. Likert Stacked Bar (if rating values 1..5)
        r_vals_distinct = set(df[r_col].dropna().round().astype(int).unique())
        if r_vals_distinct.issubset({1, 2, 3, 4, 5}):
            ct = pd.crosstab(df[c_col], df[r_col].round().astype(int), normalize="index") * 100
            fig_likert = go.Figure()
            likert_colors = ["#DC2626", "#F97316", "#FBBF24", "#34D399", "#059669"]
            for score in sorted(ct.columns):
                c_idx = min(score - 1, 4) if score >= 1 else 0
                fig_likert.add_trace(go.Bar(
                    name=f"{score} Star{'s' if score > 1 else ''}",
                    y=[str(i) for i in ct.index],
                    x=ct[score].round(1).tolist(),
                    orientation="h",
                    marker_color=likert_colors[c_idx],
                    hovertemplate="%{y}<br>" + f"{score} Stars: " + "<b>%{x:.1f}%</b><extra></extra>",
                ))
            layout_likert = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_likert["barmode"] = "stack"
            layout_likert["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title="Percentage (%)", range=[0, 100])
            layout_likert["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=c_h)
            layout_likert["legend"] = {"title": {"text": "Rating Scale"}, "orientation": "h", "y": -0.2}
            fig_likert.update_layout(**layout_likert)

            charts.append({
                "id": "chart_rating_likert",
                "title": f"{r_h} Likert Distribution by {c_h}",
                "section": "Ratings",
                "chart_type": "bar",
                "compatible_types": ["bar", "column"],
                "fields": {"x": r_col, "y": c_col, "aggregation": "distribution"},
                "figure": fig_likert.to_plotly_json(),
            })

        # 2. Average Rating Bar
        r_agg = df.dropna(subset=[r_col, c_col]).groupby(c_col)[r_col].mean().reset_index().sort_values(r_col, ascending=False)
        if len(r_agg) >= 2:
            fig_r = go.Figure()
            r_cats = r_agg[c_col].astype(str).tolist()
            r_means = [round(float(v), 2) for v in r_agg[r_col]]
            fig_r.add_trace(go.Bar(
                x=r_cats,
                y=r_means,
                marker_color="#D97706",
                text=[f"{v:.2f}" for v in r_means],
                textposition="outside",
                hovertemplate="%{x}<br>Rating: <b>%{y:.2f} / 5</b><extra></extra>",
            ))
            layout_r = dict(PLOTLY_LAYOUT_DEFAULTS)
            layout_r["yaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["yaxis"], title=f"Average {r_h} (1-5)", range=[0, 5.5])
            layout_r["xaxis"] = dict(PLOTLY_LAYOUT_DEFAULTS["xaxis"], title=c_h)
            fig_r.update_layout(**layout_r)

            charts.append({
                "id": "chart_rating_bar",
                "title": f"Average {r_h} by {c_h}",
                "section": "Ratings",
                "chart_type": "column",
                "compatible_types": ["column", "bar"],
                "fields": {"x": c_col, "y": r_col, "aggregation": "mean"},
                "figure": fig_r.to_plotly_json(),
                "x_vals": r_cats,
                "y_vals": r_means,
                "table_data": make_table_data(c_h, f"Average {r_h}", r_cats, r_means),
            })

    return charts[:12]


# ─────────────────────────────────────────────────────────────────────────────
# 5. CONSOLIDATED KEY INSIGHTS (5-8 PLAIN SENTENCES WITH EXACT NUMBERS)
# ─────────────────────────────────────────────────────────────────────────────
def compute_consolidated_insights(
    df: pd.DataFrame,
    charts: list[dict[str, Any]],
    source_meta: dict | None = None,
) -> list[dict[str, Any]]:
    insights = []
    if len(df) < 2:
        return [
            {
                "id": "insight_empty",
                "chart_id": None,
                "text": "No notable statistical anomalies or trends in the filtered data.",
                "calculation_info": "Filtered rows count < 2",
            }
        ]

    chart_lookup: dict[str, str] = {}
    for ch in charts:
        f = ch.get("fields") or {}
        if f.get("x"):
            chart_lookup[f["x"]] = ch["id"]
        if f.get("y"):
            chart_lookup[f["y"]] = ch["id"]
        chart_lookup[ch.get("section", "")] = ch["id"]

    num_cols = [c for c in df.select_dtypes("number").columns if not any(w in c.lower() for w in ("id", "phone", "pin", "roll"))]
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    date_col = date_cols[0] if date_cols else None
    primary_measure = next((c for c in num_cols if any(w in c.lower() for w in ("revenue", "sales", "amount"))), num_cols[0] if num_cols else None)

    # 1. Share / Concentration Insight
    cat_cols = [
        c for c in df.columns
        if c not in date_cols and c not in num_cols
        and not any(w in str(c).lower() for w in ("id", "code", "phone", "pin", "roll", "email", "url"))
        and 2 <= df[c].nunique() <= 20
    ]
    if primary_measure and cat_cols:
        cat = cat_cols[0]
        share_df = df.dropna(subset=[cat, primary_measure]).groupby(cat)[primary_measure].sum()
        total_m = share_df.sum()
        if total_m > 0 and len(share_df) >= 2:
            top_cat = share_df.idxmax()
            top_val = share_df.max()
            pct = round((top_val / total_m) * 100)
            target_chart = chart_lookup.get(cat, charts[0]["id"] if charts else None)
            insights.append({
                "id": "insight_share",
                "chart_id": target_chart,
                "text": f"{top_cat} generates {pct}% of {humanize_name(primary_measure).lower()}.",
                "calculation_info": f"{cat}='{top_cat}' sum({primary_measure}) = {top_val:,.0f} / total {total_m:,.0f} = {pct}%",
                "score": 0.95,
            })

    # 2. Growth / Period Trend Insight
    if date_col and primary_measure:
        ts_df = df.dropna(subset=[date_col, primary_measure]).set_index(date_col)[primary_measure].resample("MS").sum().dropna()
        if len(ts_df) >= 2:
            start_val = ts_df.iloc[0]
            end_val = ts_df.iloc[-1]
            start_mo = ts_df.index[0].strftime("%b")
            end_mo = ts_df.index[-1].strftime("%b")
            if start_val > 0:
                growth_pct = round(((end_val - start_val) / start_val) * 100)
                verb = "rose" if growth_pct >= 0 else "fell"
                abs_pct = abs(growth_pct)
                target_chart = chart_lookup.get("Trends", charts[0]["id"] if charts else None)
                insights.append({
                    "id": "insight_trend",
                    "chart_id": target_chart,
                    "text": f"{humanize_name(primary_measure)} {verb} {abs_pct}% from {start_mo} to {end_mo}.",
                    "calculation_info": f"Month-start aggregate {primary_measure}: {start_mo}={start_val:,.0f}, {end_mo}={end_val:,.0f} (delta = {growth_pct:+.1f}%)",
                    "score": 0.92,
                })

    # 3. Time Series Change-Point / Jump
    if date_col and primary_measure:
        ts_daily = df.dropna(subset=[date_col, primary_measure]).sort_values(date_col)
        if len(ts_daily) >= 12:
            mid_idx = len(ts_daily) // 2
            split_date = ts_daily.iloc[mid_idx][date_col].strftime("%b %Y")
            p1_mean = ts_daily.iloc[:mid_idx][primary_measure].mean()
            p2_mean = ts_daily.iloc[mid_idx:][primary_measure].mean()
            if p1_mean > 0:
                jump_pct = round(((p2_mean - p1_mean) / p1_mean) * 100)
                if abs(jump_pct) >= 10:
                    verb = "jumped" if jump_pct > 0 else "dipped"
                    target_chart = chart_lookup.get("Trends", charts[0]["id"] if charts else None)
                    insights.append({
                        "id": "insight_jump",
                        "chart_id": target_chart,
                        "text": f"Average {humanize_name(primary_measure).lower()} {verb} {abs(jump_pct)}% after {split_date}.",
                        "calculation_info": f"Pre-{split_date} mean = {p1_mean:,.1f}, Post-{split_date} mean = {p2_mean:,.1f}",
                        "score": 0.88,
                    })

    # 4. Outlier Count & Impact
    price_or_num = next((c for c in num_cols if any(w in c.lower() for w in ("price", "unit_price", "revenue", "amount"))), num_cols[0] if num_cols else None)
    if price_or_num:
        s = df[price_or_num].dropna().astype(float)
        if len(s) >= 8:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                hi = q3 + 1.5 * iqr
                n_out = int((s > hi).sum())
                if n_out > 0:
                    target_chart = chart_lookup.get(f"chart_dist_{price_or_num}", charts[0]["id"] if charts else None)
                    insights.append({
                        "id": "insight_outlier",
                        "chart_id": target_chart,
                        "text": f"{n_out} transactions have unusually high {humanize_name(price_or_num).lower()}.",
                        "calculation_info": f"Tukey's IQR: 1.5×IQR upper threshold = {hi:,.1f}. {n_out} values exceed threshold.",
                        "score": 0.85,
                    })

    # 5. Group Differences
    if cat_cols and primary_measure:
        cat = cat_cols[0]
        group_means = df.dropna(subset=[cat, primary_measure]).groupby(cat)[primary_measure].mean()
        if len(group_means) >= 2:
            top_group = group_means.idxmax()
            low_group = group_means.idxmin()
            ratio = group_means.max() / (group_means.min() or 1)
            if ratio >= 1.3:
                target_chart = chart_lookup.get(cat, charts[0]["id"] if charts else None)
                insights.append({
                    "id": "insight_group_diff",
                    "chart_id": target_chart,
                    "text": f"{top_group} has {ratio:.1f}x higher average {humanize_name(primary_measure).lower()} than {low_group}.",
                    "calculation_info": f"Group mean {primary_measure}: {top_group}={group_means.max():,.1f}, {low_group}={group_means.min():,.1f}",
                    "score": 0.82,
                })

    # 6. Rating Scale Comparison
    rating_col = next((c for c in num_cols if any(w in c.lower() for w in ("rating", "satisfaction", "score"))), None)
    if rating_col and cat_cols:
        cat = cat_cols[0]
        r_grp = df.dropna(subset=[cat, rating_col]).groupby(cat)[rating_col].mean()
        if len(r_grp) >= 2:
            top_cat = r_grp.idxmax()
            low_cat = r_grp.idxmin()
            diff = r_grp.max() - r_grp.min()
            if diff >= 0.2:
                target_chart = chart_lookup.get("Ratings", charts[0]["id"] if charts else None)
                insights.append({
                    "id": "insight_rating_diff",
                    "chart_id": target_chart,
                    "text": f"Customers in {top_cat} rate experience {diff:.1f} points higher than in {low_cat}.",
                    "calculation_info": f"Mean {rating_col}: {top_cat}={r_grp.max():.2f}, {low_cat}={r_grp.min():.2f}",
                    "score": 0.80,
                })

    # 7. Secondary Measure Correlation
    if primary_measure and len(num_cols) >= 2:
        sec = next((c for c in num_cols if c != primary_measure), None)
        if sec:
            sub = df[[primary_measure, sec]].dropna()
            if len(sub) >= 10:
                r = sub.corr().iloc[0, 1]
                if abs(r) >= 0.6:
                    target_chart = chart_lookup.get("Distributions", charts[0]["id"] if charts else None)
                    rel = "positively" if r > 0 else "negatively"
                    insights.append({
                        "id": "insight_corr",
                        "chart_id": target_chart,
                        "text": f"{humanize_name(primary_measure)} and {humanize_name(sec).lower()} are strongly {rel} correlated (r={r:.2f}).",
                        "calculation_info": f"Pearson r = {r:.2f} (n = {len(sub)})",
                        "score": 0.78,
                    })

    insights.sort(key=lambda x: x["score"], reverse=True)
    final_insights = insights[:8]
    currency_sym = (source_meta or {}).get("column_currencies", {}).get(primary_measure or "", "₹")

    # Pad with substantive statistical facts if < 5 insights
    if len(final_insights) < 5 and len(df) > 0:
        if primary_measure:
            mean_v = float(df[primary_measure].mean())
            final_insights.append({
                "id": "insight_baseline_mean",
                "chart_id": charts[0]["id"] if charts else None,
                "text": f"Average {humanize_name(primary_measure).lower()} is {currency_sym}{mean_v:,.2f} across all records.",
                "calculation_info": f"Dataset mean for {primary_measure}",
                "score": 0.6,
            })
            min_v = float(df[primary_measure].min())
            max_v = float(df[primary_measure].max())
            final_insights.append({
                "id": "insight_baseline_range",
                "chart_id": charts[0]["id"] if charts else None,
                "text": f"{humanize_name(primary_measure)} spans from {currency_sym}{min_v:,.2f} to {currency_sym}{max_v:,.2f}.",
                "calculation_info": f"Dataset range for {primary_measure}",
                "score": 0.55,
            })

        if cat_cols:
            c0 = cat_cols[0]
            val_counts = df[c0].value_counts()
            if len(val_counts) > 0:
                top_m = val_counts.index[0]
                top_c = int(val_counts.iloc[0])
                final_insights.append({
                    "id": "insight_top_category",
                    "chart_id": chart_lookup.get(c0, charts[0]["id"] if charts else None),
                    "text": f"'{top_m}' leads {humanize_name(c0).lower()} with {top_c:,} transactions.",
                    "calculation_info": f"Mode of {c0}",
                    "score": 0.5,
                })

        if len(num_cols) >= 2:
            sec_col = next((c for c in num_cols if c != primary_measure), None)
            if sec_col:
                s_mean = float(df[sec_col].mean())
                final_insights.append({
                    "id": "insight_sec_mean",
                    "chart_id": charts[0]["id"] if charts else None,
                    "text": f"Average {humanize_name(sec_col).lower()} stands at {s_mean:,.2f}.",
                    "calculation_info": f"Mean for {sec_col}",
                    "score": 0.45,
                })

        final_insights.append({
            "id": "insight_record_count",
            "chart_id": charts[0]["id"] if charts else None,
            "text": f"{len(df):,} total records evaluated across {len(df.columns)} dimensions and measures.",
            "calculation_info": f"Dataset row and column dimension totals",
            "score": 0.4,
        })

    return final_insights[:8]


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET DASHBOARD PAYLOAD
# ─────────────────────────────────────────────────────────────────────────────
def get_dashboard_payload(
    df_raw: pd.DataFrame,
    dataset_name: str,
    dataset_id: str,
    source_meta: dict | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # 1. Type casting
    df_prepared = clean_and_prepare_df_types(df_raw)

    # 2. Detect filters on full dataset
    available_filters = detect_available_filters(df_prepared)

    # 3. Apply active filters (including date range, slicers, cross-filter)
    df_filtered = apply_filters_to_df(df_prepared, filters)

    # 4. Compute KPIs from filtered data
    kpis = compute_kpis(df_filtered, source_meta)

    # 5. Compute suitable charts from filtered data
    charts = build_suitable_charts(df_filtered, source_meta, filters)

    # 6. Compute consolidated key insights
    insights = compute_consolidated_insights(df_filtered, charts, source_meta)

    # 7. Formatted "Data as of <timestamp>"
    last_updated_str = datetime.now().strftime("%b %d, %Y, %I:%M %p")

    # 8. Schema columns
    num_cols = [c for c in df_filtered.select_dtypes("number").columns]
    date_cols = [c for c in df_filtered.columns if pd.api.types.is_datetime64_any_dtype(df_filtered[c])]
    cat_cols = [c for c in df_filtered.columns if c not in num_cols and c not in date_cols]

    return {
        "dataset_name": dataset_name,
        "dataset_id": dataset_id,
        "total_rows": len(df_raw),
        "filtered_rows": len(df_filtered),
        "last_updated_at": last_updated_str,
        "available_filters": available_filters,
        "active_filters": filters or {},
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "schema": {
            "numeric_columns": num_cols,
            "categorical_columns": cat_cols,
            "date_columns": date_cols,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. EXECUTIVE PDF REPORT GENERATOR (REPORTLAB)
# ─────────────────────────────────────────────────────────────────────────────
def generate_executive_pdf_report(
    df_raw: pd.DataFrame,
    dataset_name: str,
    source_meta: dict | None = None,
    filters: dict[str, Any] | None = None,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    payload = get_dashboard_payload(df_raw, dataset_name, "preview", source_meta, filters)
    kpis = payload["kpis"]
    insights = payload["insights"]
    charts = payload["charts"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#101828"),
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0B7A75"),
        spaceBefore=12,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "MetaText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475467"),
    )
    kpi_num_style = ParagraphStyle(
        "KpiNum",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#101828"),
        alignment=1,
    )
    kpi_label_style = ParagraphStyle(
        "KpiLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#475467"),
        alignment=1,
    )
    insight_bullet_style = ParagraphStyle(
        "InsightBullet",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#101828"),
    )

    story = []

    # Title & Header
    story.append(Paragraph(f"DataPilot — {dataset_name}", title_style))
    story.append(Spacer(1, 4))
    date_str = pd.Timestamp.now().strftime("%B %d, %Y")
    filtered_info = f" · {payload['filtered_rows']} records" if payload['filtered_rows'] != payload['total_rows'] else f" · {payload['total_rows']} total records"
    story.append(Paragraph(f"Executive Analysis Report · Generated on {date_str}{filtered_info}", meta_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E4E7EC"), spaceAfter=12))

    # 1. KPIs Row
    story.append(Paragraph("Key Performance Indicators", section_style))
    kpi_cells = []
    for k in kpis[:5]:
        cell_flowables = [
            Paragraph(f"<b>{k['value']}</b>", kpi_num_style),
            Spacer(1, 2),
            Paragraph(k["label"], kpi_label_style),
        ]
        if k.get("delta") is not None:
            delta_color = "#059669" if k.get("is_positive") else "#DC2626"
            sign = "+" if k["delta"] > 0 else ""
            cell_flowables.append(
                Paragraph(f"<font color='{delta_color}'><b>{sign}{k['delta']}%</b></font>", kpi_label_style)
            )
        kpi_cells.append(cell_flowables)

    if kpi_cells:
        kpi_table = Table([kpi_cells], colWidths=[108] * len(kpi_cells))
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(kpi_table)

    story.append(Spacer(1, 14))

    # 2. Key Insights
    story.append(Paragraph("Key Insights", section_style))
    insight_rows = []
    for idx, ins in enumerate(insights, 1):
        p_text = f"<b>{idx}.</b> {ins['text']}"
        insight_rows.append([Paragraph(p_text, insight_bullet_style)])

    if insight_rows:
        t_ins = Table(insight_rows, colWidths=[540])
        t_ins.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBF7D0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DCFCE7")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(t_ins)

    story.append(Spacer(1, 14))

    # 3. Chart Summaries Table
    story.append(Paragraph("Visual Summaries & Distributions", section_style))
    chart_summary_rows = [
        [
            Paragraph("<b>Chart Title</b>", meta_style),
            Paragraph("<b>Category / X</b>", meta_style),
            Paragraph("<b>Measure / Y</b>", meta_style),
            Paragraph("<b>Type</b>", meta_style),
        ]
    ]
    for ch in charts[:8]:
        f = ch.get("fields") or {}
        chart_summary_rows.append([
            Paragraph(f"<b>{ch['title']}</b>", meta_style),
            Paragraph(str(f.get("x") or "-"), meta_style),
            Paragraph(str(f.get("y") or "-"), meta_style),
            Paragraph(ch["chart_type"].capitalize(), meta_style),
        ])

    ch_table = Table(chart_summary_rows, colWidths=[200, 120, 120, 100])
    ch_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
    ]))
    story.append(ch_table)

    doc.build(story)
    return buf.getvalue()
