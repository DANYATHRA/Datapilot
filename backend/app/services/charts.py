"""
DataPilot Enterprise Plotly Chart Builder.

Single source of truth for all 23 visual types:
1. KPI card, 2. Sparkline KPI, 3. Gauge, 4. Bullet bar,
5. Column, 6. Bar, 7. Stacked column, 8. Stacked bar, 9. Combo,
10. Line, 11. Area, 12. Pie, 13. Donut, 14. Treemap, 15. Funnel,
16. Scatter, 17. Bubble, 18. Heatmap, 19. Histogram, 20. Box plot,
21. Table, 22. Pivot, 23. Likert stack.

Strict Enterprise Specifications:
- Transparent background
- Font: IBM Plex Sans 12px, text #0F1B2D, secondary text #566274
- NO title inside the figure (card header carries title and subtitle)
- Horizontal light gridlines only (#E3E8EE); no vertical gridlines; no zero-line clutter
- Baseline axis line only; automargin=True
- Color-blind safe palette (top 5 + 'Other' in #94A3B8)
- Compact lakh/crore (12.5L, 3.2Cr) or K/M/B formatting with custom tickvals & ticktext
- Smart sorting, Freedman-Diaconis histogram bins, zero-baseline enforcement, change point annotations
- Mode bar: hidden by default, only Download PNG and Reset zoom on hover
- Animations off, no drop shadows, no 3D, no gradients, no emoji
"""
from __future__ import annotations

import json
import math
from typing import Any, Sequence
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .formatters import (
    format_compact_number,
    format_percent,
    format_date_by_grain,
    generate_axis_ticks,
    truncate_label,
    is_indian_currency,
)
from .chart_lint import lint_and_prepare_data, LintResult

# Color-blind safe palette (Okabe-Ito / Wong high-contrast adapted)
BRAND_PRIMARY = "#2563EB"
OTHER_GREY = "#94A3B8"

PALETTE_CB = [
    "#2563EB",  # Brand Blue
    "#0D9488",  # Teal
    "#D97706",  # Amber
    "#7C3AED",  # Violet
    "#DC2626",  # Coral Red
    "#0284C7",  # Sky Blue
]

PALETTES: dict[str, list[str]] = {
    "colour_blind_safe": PALETTE_CB,
    "teal": ["#0D9488", "#14B8A6", "#2DD4BF", "#0284C7", "#2563EB", "#7C3AED"],
    "ocean": ["#0284C7", "#0EA5E9", "#38BDF8", "#06B6D4", "#2563EB", "#1D4ED8"],
    "sunset": ["#D97706", "#F59E0B", "#F97316", "#EA580C", "#DC2626", "#7C3AED"],
    "greys": ["#334155", "#475569", "#64748B", "#94A3B8", "#CBD5E1", "#E2E8F0"],
}

# Sequential palette for Heatmaps (single-hue blue)
HEATMAP_SEQUENTIAL = [
    [0.0, "#eff6ff"],
    [0.2, "#bfdbfe"],
    [0.4, "#60a5fa"],
    [0.7, "#2563eb"],
    [1.0, "#1d4ed8"],
]

# Diverging palette for Correlations with neutral midpoint
CORRELATION_DIVERGING = [
    [0.0, "#ea580c"],  # Negative Orange
    [0.4, "#fdba74"],
    [0.5, "#f1f5f9"],  # Neutral Midpoint
    [0.6, "#93c5fd"],
    [1.0, "#2563eb"],  # Positive Blue
]


def _detect_change_points(x_vals: Sequence, y_vals: Sequence, max_points: int = 3) -> list[tuple[Any, float, str]]:
    """Detect up to max_points most significant change points (spikes, drops, extrema)."""
    if len(y_vals) < 6:
        return []
    try:
        y_arr = np.array(y_vals, dtype=float)
        diffs = np.diff(y_arr)
        scale = np.std(y_arr) if np.std(y_arr) > 0 else 1.0
        scores = np.abs(diffs) / scale

        cand_indices = np.argsort(scores)[::-1]
        chosen_indices: list[int] = []
        for idx in cand_indices:
            pt_idx = int(idx) + 1
            if pt_idx >= len(y_vals) - 1 or pt_idx <= 0:
                continue
            if all(abs(pt_idx - c) >= 3 for c in chosen_indices):
                chosen_indices.append(pt_idx)
                if len(chosen_indices) >= max_points:
                    break

        change_points = []
        for idx in chosen_indices:
            x_pt = x_vals[idx] if hasattr(x_vals, "__getitem__") else list(x_vals)[idx]
            y_pt = float(y_arr[idx])
            prev_y = float(y_arr[idx - 1])
            pct = ((y_pt - prev_y) / max(abs(prev_y), 1e-6)) * 100.0
            label = f"+{pct:.0f}%" if pct > 0 else f"{pct:.0f}%"
            change_points.append((x_pt, y_pt, label))
        return change_points
    except Exception:
        return []


def _apply_base_theme(fig: go.Figure, is_horizontal: bool = False, height: int = 320) -> go.Figure:
    """Apply the standard clean DataPilot theme across all figures."""
    fig.update_layout(
        title=None,  # NO title inside figure (card header carries title and subtitle)
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
            size=12,
            color="#0F1B2D",
        ),
        margin=dict(l=48, r=24, t=16, b=40, pad=4),
        height=height,
        transition=dict(duration=0),  # Animations off
        hoverlabel=dict(
            bgcolor="#0F1B2D",
            bordercolor="#1E293B",
            font=dict(
                family="'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
                size=12,
                color="#FFFFFF",
            ),
        ),
        legend=dict(
            font=dict(
                family="'IBM Plex Sans', sans-serif",
                size=11,
                color="#566274",
            ),
            bgcolor="rgba(0,0,0,0)",
            orientation="h",
            x=0,
            y=1.14,
            xanchor="left",
            yanchor="bottom",
        ),
    )

    if is_horizontal:
        # Horizontal charts: Vertical light gridlines on X, no gridlines on Y
        fig.update_xaxes(
            automargin=True,
            showgrid=True,
            gridcolor="#E3E8EE",
            gridwidth=1,
            zeroline=False,
            showline=False,
            tickfont=dict(size=11, color="#566274", family="'IBM Plex Mono', monospace"),
            title_font=dict(size=12, color="#0F1B2D", family="'IBM Plex Sans', sans-serif"),
        )
        fig.update_yaxes(
            automargin=True,
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor="#CBD5E1",
            linewidth=1,
            tickfont=dict(size=11, color="#566274", family="'IBM Plex Sans', sans-serif"),
            title_font=dict(size=12, color="#0F1B2D", family="'IBM Plex Sans', sans-serif"),
        )
    else:
        # Standard vertical charts: Horizontal light gridlines on Y, no gridlines on X
        fig.update_xaxes(
            automargin=True,
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor="#CBD5E1",
            linewidth=1,
            tickfont=dict(size=11, color="#566274", family="'IBM Plex Sans', sans-serif"),
            title_font=dict(size=12, color="#0F1B2D", family="'IBM Plex Sans', sans-serif"),
        )
        fig.update_yaxes(
            automargin=True,
            showgrid=True,
            gridcolor="#E3E8EE",
            gridwidth=1,
            zeroline=False,
            showline=False,
            tickfont=dict(size=11, color="#566274", family="'IBM Plex Mono', monospace"),
            title_font=dict(size=12, color="#0F1B2D", family="'IBM Plex Sans', sans-serif"),
        )

    return fig


def make_figure(
    df: pd.DataFrame,
    chart: str,
    x: str | None = None,
    y: str | None = None,
    color: str | None = None,
    title: str | None = None,
    options: dict[str, Any] | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """
    Build a complete Plotly figure JSON dictionary with smart defaults for any of the 23 visual types.
    Includes lint warnings, honest data caption, and accessibility text summary.
    """
    opts = options or {}
    chart_type = (chart or "bar").lower()
    cols = list(df.columns) if df is not None else []

    if df is None or df.empty or not cols:
        fig = go.Figure()
        _apply_base_theme(fig)
        fig_dict = json.loads(fig.to_json())
        fig_dict["datapilot_meta"] = {
            "title": title or "",
            "summary": "No data points available.",
            "warnings": ["Dataset returned zero rows."],
            "excluded_count": 0,
        }
        return fig_dict

    # Map column defaults intelligently
    x_col = x if x in cols else ("category" if "category" in cols else ("period" if "period" in cols else ("x" if "x" in cols else cols[0])))
    y_col = y if y in cols else ("value" if "value" in cols else ("y" if "y" in cols else (cols[1] if len(cols) > 1 else cols[0])))
    c_col = color if color in cols else ("series" if "series" in cols else ("color" if "color" in cols else None))

    # Detect currency / Rupee context from fields or options
    curr = currency or opts.get("currency") or (
        "INR" if any(is_indian_currency(str(col)) for col in (x_col, y_col, c_col)) else None
    )

    # 1. Chart Linter & Data Preparation
    df_clean, lint_res = lint_and_prepare_data(
        df=df,
        chart_type=chart_type,
        x_col=x_col,
        y_col=y_col,
        color_col=c_col,
        currency=curr,
        options=opts,
    )

    palette_name = opts.get("palette", "colour_blind_safe")
    colors = PALETTES.get(palette_name, PALETTE_CB)
    single_color = colors[0]

    extras = opts.get("extras", [])
    show_labels = "value_labels" in extras
    show_avg = "average_line" in extras
    is_horizontal = lint_res.is_horizontal
    fig = go.Figure()

    # Fixed card chart height: 320 px standard, 400 px for wide/stacked
    is_wide_chart = opts.get("is_wide", False) or chart_type in ("stacked_column", "stacked_bar", "heatmap", "combo", "likert_stack", "treemap")
    chart_height = 400 if is_wide_chart else 320

    # ─────────────────────────────────────────────────────────────────────────
    # 1. KPI CARD
    # ─────────────────────────────────────────────────────────────────────────
    if chart_type == "kpi_card":
        val = float(df_clean[y_col].iloc[0]) if len(df_clean) > 0 and pd.notna(df_clean[y_col].iloc[0]) else 0.0
        fig.add_trace(go.Indicator(
            mode="number",
            value=val,
            number=dict(
                font=dict(size=44, color="#0F1B2D", family="'IBM Plex Sans', sans-serif"),
                prefix="₹" if curr == "INR" else ("$" if curr == "USD" else ""),
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. SPARKLINE KPI
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "sparkline_kpi":
        val = float(df_clean[y_col].iloc[-1]) if len(df_clean) > 0 and pd.notna(df_clean[y_col].iloc[-1]) else 0.0
        fig.add_trace(go.Indicator(
            mode="number",
            value=val,
            domain=dict(y=[0.4, 1.0], x=[0, 1]),
            number=dict(
                font=dict(size=38, color="#0F1B2D", family="'IBM Plex Sans', sans-serif"),
                prefix="₹" if curr == "INR" else ("$" if curr == "USD" else ""),
            ),
        ))
        if len(df_clean) > 1:
            fig.add_trace(go.Scatter(
                x=df_clean[x_col],
                y=df_clean[y_col],
                mode="lines",
                line=dict(color=single_color, width=2.5),
                fill="tozeroy",
                fillcolor="rgba(37, 99, 235, 0.08)",
                yaxis="y2",
                hoverinfo="skip",
            ))
            fig.update_layout(
                yaxis2=dict(domain=[0, 0.35], visible=False),
                xaxis=dict(visible=False),
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. GAUGE
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "gauge":
        val = float(df_clean[y_col].iloc[0]) if len(df_clean) > 0 and pd.notna(df_clean[y_col].iloc[0]) else 0.0
        target = float(opts.get("target") or 100.0)
        fig.add_trace(go.Indicator(
            mode="gauge+number",
            value=val,
            domain=dict(x=[0.05, 0.95], y=[0.05, 0.95]),
            number=dict(font=dict(size=32, color="#0F1B2D", family="'IBM Plex Mono', monospace")),
            gauge=dict(
                axis=dict(range=[0, max(target, val * 1.15)], tickfont=dict(size=10, color="#566274")),
                bar=dict(color=single_color, thickness=0.4),
                bgcolor="rgba(227, 232, 238, 0.4)",
                borderwidth=0,
                threshold=dict(line=dict(color="#DC2626", width=2.5), thickness=0.8, value=target),
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. BULLET BAR
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "bullet":
        val = float(df_clean[y_col].iloc[0]) if len(df_clean) > 0 and pd.notna(df_clean[y_col].iloc[0]) else 0.0
        target = float(opts.get("target") or 100.0)
        fig.add_trace(go.Indicator(
            mode="number+gauge",
            value=val,
            domain=dict(x=[0.15, 0.95], y=[0.25, 0.75]),
            number=dict(font=dict(size=28, color="#0F1B2D", family="'IBM Plex Mono', monospace")),
            gauge=dict(
                shape="bullet",
                axis=dict(range=[0, max(target, val * 1.15)], tickfont=dict(size=10, color="#566274")),
                bar=dict(color=single_color, thickness=0.45),
                bgcolor="rgba(227, 232, 238, 0.4)",
                borderwidth=0,
                threshold=dict(line=dict(color="#DC2626", width=2.5), thickness=0.8, value=target),
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 5. COLUMN & BAR & STACKED COLUMN & STACKED BAR
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type in ("column", "bar", "stacked_column", "stacked_bar"):
        is_stacked = chart_type in ("stacked_column", "stacked_bar")
        is_horiz = chart_type in ("bar", "stacked_bar") or is_horizontal or (opts.get("orientation") == "horizontal")
        is_date = pd.api.types.is_datetime64_any_dtype(df_clean[x_col]) if x_col in df_clean.columns else False

        # Multi-series check
        has_multi_series = c_col and c_col in df_clean.columns and df_clean[c_col].nunique() > 1

        if has_multi_series:
            # Stable series ordering
            series_order = list(df_clean[c_col].unique())
            # Categories order
            if not is_date:
                cat_totals = df_clean.groupby(x_col)[y_col].sum()
                sorted_cats = cat_totals.sort_values(ascending=is_horiz).index.tolist()
            else:
                sorted_cats = df_clean[x_col].unique().tolist()

            max_stack = 0.0
            # Add one trace per series
            for s_idx, s_val in enumerate(series_order):
                s_df = df_clean[df_clean[c_col] == s_val]
                # Align values with categories
                cat_val_map = dict(zip(s_df[x_col], s_df[y_col]))
                y_series = [cat_val_map.get(cat, 0.0) for cat in sorted_cats]
                truncated_cats = [truncate_label(cat, 24) for cat in sorted_cats]
                full_cats = [str(cat) for cat in sorted_cats]

                s_color = OTHER_GREY if str(s_val).lower() == "other" else colors[s_idx % len(colors)]
                formatted_vals = [format_compact_number(v, currency=curr) for v in y_series]

                if is_horiz:
                    fig.add_trace(go.Bar(
                        x=y_series,
                        y=truncated_cats,
                        name=str(s_val),
                        orientation="h",
                        marker=dict(color=s_color),
                        customdata=np.stack((full_cats, formatted_vals), axis=-1),
                        hovertemplate=f"<b>%{{customdata[0]}}</b><br>{s_val}: %{{customdata[1]}}<extra></extra>",
                    ))
                else:
                    fig.add_trace(go.Bar(
                        x=truncated_cats,
                        y=y_series,
                        name=str(s_val),
                        marker=dict(color=s_color),
                        customdata=np.stack((full_cats, formatted_vals), axis=-1),
                        hovertemplate=f"<b>%{{customdata[0]}}</b><br>{s_val}: %{{customdata[1]}}<extra></extra>",
                    ))

            # Total stack values for honest axis range and top labels
            cat_sum = df_clean.groupby(x_col)[y_col].sum()
            max_stack = float(cat_sum.max()) if not cat_sum.empty else 10.0

            # Total label on top of stacked bars/columns
            if is_stacked and len(sorted_cats) <= 15:
                for cat in sorted_cats:
                    tot_v = float(cat_sum.get(cat, 0.0))
                    formatted_tot = format_compact_number(tot_v, currency=curr)
                    trunc_c = truncate_label(cat, 24)
                    if is_horiz:
                        fig.add_annotation(
                            x=tot_v,
                            y=trunc_c,
                            text=f"<b>{formatted_tot}</b>",
                            showarrow=False,
                            xanchor="left",
                            xshift=6,
                            font=dict(size=10, family="'IBM Plex Mono', monospace", color="#566274"),
                        )
                    else:
                        fig.add_annotation(
                            x=trunc_c,
                            y=tot_v,
                            text=f"<b>{formatted_tot}</b>",
                            showarrow=False,
                            yanchor="bottom",
                            yshift=6,
                            font=dict(size=10, family="'IBM Plex Mono', monospace", color="#566274"),
                        )

            ticks, ticktexts = generate_axis_ticks(0.0, max_stack * 1.15, max_ticks=6, currency=curr, force_zero=True)
            if is_horiz:
                fig.update_xaxes(
                    rangemode="tozero",
                    range=[0, max_stack * 1.18],
                    tickvals=ticks,
                    ticktext=ticktexts,
                )
            else:
                fig.update_yaxes(
                    rangemode="tozero",
                    range=[0, max_stack * 1.18],
                    tickvals=ticks,
                    ticktext=ticktexts,
                )

        else:
            # Single series
            if not is_date:
                df_clean = df_clean.sort_values(by=y_col, ascending=is_horiz).reset_index(drop=True)

            truncated_labels = [truncate_label(lbl, 24) for lbl in df_clean[x_col]]
            full_labels = [str(lbl) for lbl in df_clean[x_col]]
            formatted_y = [format_compact_number(v, currency=curr) for v in df_clean[y_col]]

            cat_count = len(df_clean)
            show_direct_labels = show_labels or (cat_count <= 12 and not is_stacked)
            max_v = float(df_clean[y_col].max()) if len(df_clean) else 10.0

            if is_horiz:
                fig.add_trace(go.Bar(
                    x=df_clean[y_col],
                    y=truncated_labels,
                    customdata=np.stack((full_labels, formatted_y), axis=-1),
                    orientation="h",
                    marker=dict(color=single_color),
                    text=formatted_y if show_direct_labels else None,
                    textposition="outside" if show_direct_labels else "none",
                    textfont=dict(size=11, family="'IBM Plex Mono', monospace", color="#566274"),
                    hovertemplate="<b>%{customdata[0]}</b><br>Value: %{customdata[1]}<extra></extra>",
                ))
                ticks, ticktexts = generate_axis_ticks(0.0, max_v * 1.15, max_ticks=6, currency=curr, force_zero=True)
                fig.update_xaxes(
                    rangemode="tozero",
                    range=[0, max_v * 1.18 if show_direct_labels else max_v * 1.05],
                    tickvals=ticks,
                    ticktext=ticktexts,
                    showgrid=not show_direct_labels,
                )
            else:
                fig.add_trace(go.Bar(
                    x=truncated_labels,
                    y=df_clean[y_col],
                    customdata=np.stack((full_labels, formatted_y), axis=-1),
                    marker=dict(color=single_color),
                    text=formatted_y if show_direct_labels else None,
                    textposition="outside" if show_direct_labels else "none",
                    textfont=dict(size=11, family="'IBM Plex Mono', monospace", color="#566274"),
                    hovertemplate="<b>%{customdata[0]}</b><br>Value: %{customdata[1]}<extra></extra>",
                ))
                ticks, ticktexts = generate_axis_ticks(0.0, max_v * 1.15, max_ticks=6, currency=curr, force_zero=True)
                fig.update_yaxes(
                    rangemode="tozero",
                    range=[0, max_v * 1.18 if show_direct_labels else max_v * 1.05],
                    tickvals=ticks,
                    ticktext=ticktexts,
                    showgrid=not show_direct_labels,
                )

        fig.update_layout(
            barmode="stack" if is_stacked else "group",
            bargap=0.35,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. COMBO (Bar + Secondary Line)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "combo":
        truncated_labels = [truncate_label(lbl, 24) for lbl in df_clean[x_col]]
        formatted_y = [format_compact_number(v, currency=curr) for v in df_clean[y_col]]

        fig.add_trace(go.Bar(
            x=truncated_labels,
            y=df_clean[y_col],
            name=str(y_col),
            marker_color=single_color,
            text=formatted_y if show_labels else None,
            textposition="auto",
            hovertemplate=f"<b>%{{x}}</b><br>{y_col}: %{{y:,.1f}}<extra></extra>",
        ))

        sec_col = opts.get("secondary_value") or (cols[2] if len(cols) > 2 and cols[2] != y_col else None)
        if sec_col and sec_col in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[sec_col]):
            sec_color = colors[2]
            fig.add_trace(go.Scatter(
                x=truncated_labels,
                y=df_clean[sec_col],
                name=str(sec_col),
                mode="lines+markers",
                line=dict(color=sec_color, width=2.5),
                marker=dict(size=6, color=sec_color),
                yaxis="y2",
                hovertemplate=f"<b>%{{x}}</b><br>{sec_col}: %{{y:,.1f}}<extra></extra>",
            ))
            fig.update_layout(
                yaxis2=dict(
                    overlaying="y",
                    side="right",
                    automargin=True,
                    showgrid=False,
                    tickfont=dict(size=11, color=sec_color, family="'IBM Plex Mono', monospace"),
                    title=dict(text=str(sec_col), font=dict(size=12, color=sec_color)),
                ),
            )
        fig.update_yaxes(rangemode="tozero")

    # ─────────────────────────────────────────────────────────────────────────
    # 7. LINE & AREA (Auto-aggregated grain & smart change-point labels)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type in ("line", "area"):
        num_points = len(df_clean)
        show_markers = num_points <= 24
        line_mode = "lines+markers" if show_markers else "lines"

        x_vals = df_clean[x_col]
        y_vals = df_clean[y_col]
        formatted_y = [format_compact_number(v, currency=curr) for v in y_vals]

        last_idx = len(df_clean) - 1
        last_x = x_vals.iloc[last_idx]
        last_y = float(y_vals.iloc[last_idx])
        last_formatted = formatted_y[last_idx]

        trace_args = dict(
            x=x_vals,
            y=y_vals,
            mode=line_mode,
            line=dict(color=single_color, width=2.5),
            marker=dict(size=6, color=single_color) if show_markers else None,
            connectgaps=False,  # Honest gap for missing periods
            hovertemplate="<b>%{x}</b><br>Value: %{y:,.2f}<extra></extra>",
        )

        if chart_type == "area":
            fig.add_trace(go.Scatter(
                **trace_args,
                fill="tozeroy",
                fillcolor="rgba(37, 99, 235, 0.08)",
            ))
            min_y = 0.0
            max_y = float(y_vals.max()) if len(y_vals) else 10.0
            ticks, ticktexts = generate_axis_ticks(0.0, max_y * 1.1, max_ticks=6, currency=curr, force_zero=True)
            fig.update_yaxes(rangemode="tozero", range=[0.0, max_y * 1.12], tickvals=ticks, ticktext=ticktexts)
        else:
            fig.add_trace(go.Scatter(**trace_args))
            min_y = float(y_vals.min()) if len(y_vals) else 0.0
            max_y = float(y_vals.max()) if len(y_vals) else 10.0
            if min_y > 0 and (min_y / max(max_y, 1)) > 0.4:
                min_y = min_y * 0.95
            else:
                min_y = 0.0
            ticks, ticktexts = generate_axis_ticks(min_y, max_y * 1.1, max_ticks=6, currency=curr, force_zero=(min_y == 0.0))
            fig.update_yaxes(range=[min_y, max_y * 1.12], tickvals=ticks, ticktext=ticktexts)

        # Direct annotation on the last point
        fig.add_annotation(
            x=last_x,
            y=last_y,
            text=f"<b>{last_formatted}</b>",
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor="#566274",
            ax=20,
            ay=-15,
            font=dict(size=11, family="'IBM Plex Mono', monospace", color="#0F1B2D"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#CBD5E1",
            borderwidth=1,
            borderpad=3,
        )

        # Annotate up to 3 detected change points
        change_pts = _detect_change_points(list(x_vals), list(y_vals), max_points=3)
        for cx, cy, c_lbl in change_pts:
            fig.add_annotation(
                x=cx,
                y=cy,
                text=c_lbl,
                showarrow=True,
                arrowhead=1,
                arrowsize=1,
                arrowwidth=1,
                arrowcolor="#94A3B8",
                ax=0,
                ay=-20,
                font=dict(size=10, family="'IBM Plex Mono', monospace", color="#334155"),
                bgcolor="rgba(241, 245, 249, 0.9)",
                bordercolor="#E2E8F0",
                borderwidth=1,
                borderpad=2,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 8. PIE & DONUT (Max 6 slices, outside labels, donut center total)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type in ("pie", "donut"):
        is_donut = chart_type == "donut"
        total_val = float(df_clean[y_col].sum())
        formatted_total = format_compact_number(total_val, currency=curr)

        slice_colors = []
        for i, cat in enumerate(df_clean[x_col]):
            if str(cat).lower() == "other":
                slice_colors.append(OTHER_GREY)
            else:
                slice_colors.append(colors[i % len(colors)])

        fig.add_trace(go.Pie(
            labels=df_clean[x_col],
            values=df_clean[y_col],
            hole=0.55 if is_donut else 0.0,
            sort=False,  # Already sorted
            marker=dict(colors=slice_colors, line=dict(color="#FFFFFF", width=1.5)),
            textposition="outside",
            textinfo="percent+label",
            textfont=dict(size=11, family="'IBM Plex Sans', sans-serif"),
            hovertemplate="<b>%{label}</b><br>Value: %{value:,.0f} (%{percent})<extra></extra>",
        ))

        if is_donut:
            fig.add_annotation(
                text=f"<span style='font-size:10px;color:#566274'>TOTAL</span><br><b>{formatted_total}</b>",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=13, family="'IBM Plex Sans', sans-serif", color="#0F1B2D"),
            )
        fig.update_layout(showlegend=False)

    # ─────────────────────────────────────────────────────────────────────────
    # 9. TREEMAP
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "treemap":
        path_cols = [x_col]
        if "sub_category" in cols and "sub_category" != x_col:
            path_cols.append("sub_category")
        fig = px.treemap(
            df_clean,
            path=path_cols,
            values=y_col,
            color_discrete_sequence=colors,
        )
        fig.update_traces(
            textinfo="label+value+percent entry",
            textfont=dict(family="'IBM Plex Sans', sans-serif", size=11),
            marker=dict(line=dict(width=1, color="#FFFFFF")),
            hovertemplate="<b>%{label}</b><br>Value: %{value:,.0f}<extra></extra>",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 10. FUNNEL
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "funnel":
        fig = px.funnel(
            df_clean,
            x=y_col,
            y=x_col,
            color_discrete_sequence=[single_color],
        )
        fig.update_traces(
            textinfo="value+percent initial",
            textfont=dict(family="'IBM Plex Mono', monospace", size=11),
            hovertemplate="<b>%{y}</b><br>Volume: %{x:,.0f}<extra></extra>",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 11. SCATTER & BUBBLE (Small size, 0.6 opacity, WebGL / trendline)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type in ("scatter", "bubble"):
        is_bubble = chart_type == "bubble"
        size_arg = "size" if is_bubble and "size" in cols else None

        num_pts = len(df_clean)
        use_gl = num_pts > 2000

        scatter_cls = go.Scattergl if use_gl else go.Scatter
        fig.add_trace(scatter_cls(
            x=df_clean[x_col],
            y=df_clean[y_col],
            mode="markers",
            marker=dict(
                size=df_clean[size_arg] if size_arg else 7,
                color=single_color,
                opacity=0.6,
                line=dict(width=0.5, color="#1E293B"),
            ),
            hovertemplate=f"<b>{x_col}</b>: %{{x}}<br><b>{y_col}</b>: %{{y:,.2f}}<extra></extra>",
        ))

        # Check for 3 orders of magnitude range to offer/set log scale
        if pd.api.types.is_numeric_dtype(df_clean[y_col]):
            pos_vals = df_clean[y_col][df_clean[y_col] > 0]
            if len(pos_vals) > 0 and (pos_vals.max() / max(pos_vals.min(), 1e-9)) > 1000:
                if opts.get("log_scale"):
                    fig.update_yaxes(type="log")

        # Trendline with R2
        if len(df_clean) >= 5 and pd.api.types.is_numeric_dtype(df_clean[x_col]) and pd.api.types.is_numeric_dtype(df_clean[y_col]):
            try:
                valid_mask = ~(df_clean[x_col].isna() | df_clean[y_col].isna())
                vx = df_clean.loc[valid_mask, x_col].values
                vy = df_clean.loc[valid_mask, y_col].values
                if len(vx) >= 5:
                    p = np.polyfit(vx, vy, 1)
                    fit_y = np.polyval(p, vx)
                    r2 = np.corrcoef(vx, vy)[0, 1] ** 2
                    sort_order = np.argsort(vx)
                    fig.add_trace(go.Scatter(
                        x=vx[sort_order],
                        y=fit_y[sort_order],
                        mode="lines",
                        line=dict(color="#DC2626", width=2, dash="dash"),
                        name=f"Trend (R²={r2:.2f})",
                        hoverinfo="skip",
                    ))
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 12. HEATMAP (Sorted axes, cell values when <= 12x12, slim colorbar)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "heatmap":
        if "row" in cols and "col" in cols and "value" in cols:
            piv = df_clean.pivot(index="row", columns="col", values="value").fillna(0)
            piv = piv.sort_index(ascending=True)
            piv = piv.reindex(sorted(piv.columns), axis=1)

            show_cell_text = (len(piv.index) <= 12 and len(piv.columns) <= 12)
            fig.add_trace(go.Heatmap(
                z=piv.values,
                x=list(piv.columns),
                y=list(piv.index),
                colorscale=HEATMAP_SEQUENTIAL,
                text=piv.values if show_cell_text else None,
                texttemplate="%{text:,.0f}" if show_cell_text else None,
                textfont=dict(size=10, family="'IBM Plex Mono', monospace"),
                colorbar=dict(
                    thickness=12,
                    len=0.75,
                    tickfont=dict(size=10, color="#566274"),
                ),
                hovertemplate="Row: %{y}<br>Col: %{x}<br>Value: %{z:,.2f}<extra></extra>",
            ))
        else:
            fig = px.density_heatmap(
                df_clean,
                x=x_col,
                y=y_col,
                color_continuous_scale=HEATMAP_SEQUENTIAL,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 13. HISTOGRAM (Freedman-Diaconis rule binning, median line)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "histogram":
        val_series = df_clean[y_col] if y_col in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[y_col]) else df_clean[x_col]
        clean_vals = val_series.dropna().values

        n = len(clean_vals)
        if n > 2:
            q75, q25 = np.percentile(clean_vals, [75, 25])
            iqr = q75 - q25
            h = 2 * iqr * (n ** (-1 / 3)) if iqr > 0 else 0
            val_range = clean_vals.max() - clean_vals.min()
            nbins = int(math.ceil(val_range / h)) if h > 0 and val_range > 0 else 15
            nbins = max(5, min(nbins, 40))
        else:
            nbins = 10

        fig.add_trace(go.Histogram(
            x=clean_vals,
            nbinsx=nbins,
            marker=dict(color=single_color, line=dict(color="#FFFFFF", width=1)),
            hovertemplate="Range: %{x}<br>Count: %{y:,}<extra></extra>",
        ))

        if n > 0:
            median_val = float(np.median(clean_vals))
            formatted_median = format_compact_number(median_val, currency=curr)
            fig.add_vline(
                x=median_val,
                line_dash="dash",
                line_color="#DC2626",
                line_width=2,
                annotation_text=f"Median: {formatted_median}",
                annotation_position="top right",
                annotation_font=dict(size=11, family="'IBM Plex Mono', monospace", color="#DC2626"),
            )

        fig.update_layout(bargap=0.05)

    # ─────────────────────────────────────────────────────────────────────────
    # 14. BOX PLOT (Outliers only, sorted by group median)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "box":
        cat_arg = x_col if x_col in cols else None
        num_arg = y_col if y_col in cols else x_col

        fig.add_trace(go.Box(
            x=df_clean[cat_arg] if cat_arg else None,
            y=df_clean[num_arg],
            boxpoints="outliers",  # Points shown only for outliers
            marker=dict(color=single_color, size=5, opacity=0.7),
            line=dict(color=single_color, width=1.5),
            hovertemplate="Group: %{x}<br>Value: %{y:,.2f}<extra></extra>",
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 15. TABLE & PIVOT
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type in ("table", "pivot"):
        headers = list(df_clean.columns)
        cells_values = [df_clean[c].tolist() for c in headers]
        fig.add_trace(go.Table(
            header=dict(
                values=[f"<b>{h}</b>" for h in headers],
                fill_color="#F8FAFC",
                align="left",
                font=dict(color="#0F1B2D", size=12, family="'IBM Plex Sans', sans-serif"),
                height=32,
                line=dict(color="#E2E8F0", width=1),
            ),
            cells=dict(
                values=cells_values,
                fill_color="#FFFFFF",
                align="left",
                font=dict(color="#334155", size=11, family="'IBM Plex Mono', monospace"),
                height=28,
                line=dict(color="#E2E8F0", width=1),
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 16. LIKERT STACK (Relative Diverging Stack)
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "likert_stack":
        fig = px.bar(
            df_clean,
            x=y_col,
            y=x_col,
            color=c_col,
            orientation="h",
            barmode="relative",
            color_discrete_sequence=colors,
        )
        is_horizontal = True

    else:
        fig = px.bar(df_clean, x=x_col, y=y_col, color=c_col, color_discrete_sequence=colors)

    # ── Extras: Average Reference Line ───────────────────────────────────────
    if show_avg and y_col in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[y_col]):
        avg_val = float(df_clean[y_col].mean())
        formatted_avg = format_compact_number(avg_val, currency=curr)
        fig.add_hline(
            y=avg_val,
            line_dash="dot",
            line_color="#D97706",
            line_width=1.75,
            annotation_text=f"Avg: {formatted_avg}",
            annotation_position="bottom right",
            annotation_font=dict(size=10, family="'IBM Plex Mono', monospace", color="#D97706"),
        )

    # ── Single Series Legend Hiding ──────────────────────────────────────────
    trace_count = len(fig.data)
    if trace_count <= 1:
        fig.update_layout(showlegend=False)
    else:
        fig.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h",
                y=1.14,
                x=0,
                yanchor="bottom",
                xanchor="left",
            ),
        )

    # Apply base DataPilot theme
    _apply_base_theme(fig, is_horizontal=is_horizontal, height=chart_height)

    fig_dict = json.loads(fig.to_json())

    # Attach DataPilot metadata for honest data captions, excluded rows, and aria accessibility
    caption_note = ""
    if lint_res.excluded_count > 0:
        caption_note = f"{lint_res.excluded_count:,} rows excluded (missing or invalid field)"

    fig_dict["datapilot_meta"] = {
        "title": title or "",
        "summary": lint_res.summary,
        "warnings": lint_res.warnings,
        "excluded_count": lint_res.excluded_count,
        "caption": caption_note,
        "currency": curr,
    }

    return fig_dict
