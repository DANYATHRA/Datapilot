"""
Comprehensive Test Suite for DataPilot Chart Presentation, Linter, and Formatting.

Tests:
1. Formatters: Indian Lakh/Crore (₹12.5L, ₹3.2Cr), K/M/B, percentages, date grains, label truncation.
2. Custom Axis Ticks: 5-8 ticks with exact lakh/crore ticktext mapping.
3. Linter Rules:
   - >30 categories collapsed to Top 10 + "Other".
   - Total conservation: sum(values) after grouping exactly matches original total.
   - Pie capped at <=6 slices (remainder in "Other").
   - Negative values in composition flagged.
   - Auto-horizontal flip for >7 categories or labels >8 characters.
   - Zero baseline on bar/column and area figures.
   - Auto-aggregation on dense time series (<= 60 points).
4. Accessibility & Honest Data:
   - Aria summary matches pandas metrics (highest category, % share).
   - Excluded rows count & honest caption.
"""
from __future__ import annotations

import datetime as dt
import numpy as np
import pandas as pd
import pytest

try:
    from app.services.formatters import (
        format_compact_number,
        format_percent,
        format_date_by_grain,
        truncate_label,
        generate_axis_ticks,
        is_indian_currency,
    )
    from app.services.chart_lint import (
        lint_and_prepare_data,
        generate_accessible_summary,
        LintResult,
    )
    from app.services.charts import make_figure
except ImportError:
    from backend.app.services.formatters import (
        format_compact_number,
        format_percent,
        format_date_by_grain,
        truncate_label,
        generate_axis_ticks,
        is_indian_currency,
    )
    from backend.app.services.chart_lint import (
        lint_and_prepare_data,
        generate_accessible_summary,
        LintResult,
    )
    from backend.app.services.charts import make_figure


# ─────────────────────────────────────────────────────────────────────────────
# 1. NUMBER & DATE FORMATTING TESTS
# ─────────────────────────────────────────────────────────────────────────────
class TestFormatters:
    def test_indian_lakh_crore_formatting(self):
        # 1.2 Lakh
        assert format_compact_number(120000, currency="INR") == "₹1.2L"
        # 12.5 Lakh
        assert format_compact_number(1250000, currency="INR") == "₹12.5L"
        # 3.2 Crore
        assert format_compact_number(32000000, currency="INR") == "₹3.2Cr"
        # Negative Lakh
        assert format_compact_number(-2500000, currency="INR") == "-₹25.0L"
        # Below Lakh
        assert format_compact_number(45000, currency="INR") == "₹45.0K"

    def test_standard_compact_number_formatting(self):
        assert format_compact_number(950) == "950"
        assert format_compact_number(1500) == "1.5K"
        assert format_compact_number(2450000) == "2.5M"
        assert format_compact_number(1200000000) == "1.2B"
        assert format_compact_number(5000, currency="USD") == "$5.0K"

    def test_percent_formatting(self):
        assert format_percent(45.678) == "45.7%"
        assert format_percent(100.0) == "100.0%"
        assert format_percent(0.0) == "0.0%"

    def test_date_grain_formatting(self):
        d = dt.date(2025, 1, 15)
        assert format_date_by_grain(d, "day") == "15 Jan 2025"
        assert format_date_by_grain(d, "month") == "Jan 2025"
        assert format_date_by_grain(d, "quarter") == "Q1 2025"
        assert format_date_by_grain(d, "year") == "2025"

    def test_label_truncation(self):
        short_label = "North Region"
        assert truncate_label(short_label, max_len=24) == "North Region"

        long_label = "Enterprise Software and Cloud Infrastructure Services"
        truncated = truncate_label(long_label, max_len=24)
        assert len(truncated) <= 24
        assert truncated.endswith("...")

    def test_custom_axis_ticks_lakh_crore(self):
        # Test axis ticks for values up to 5 Crore
        vals = [0, 10000000, 20000000, 30000000, 40000000, 50000000]
        tickvals, ticktext = generate_axis_ticks(vals, currency="INR", max_ticks=7)
        assert len(tickvals) >= 4 and len(tickvals) <= 8
        assert len(tickvals) == len(ticktext)
        # Check that top tick text has Cr suffix
        assert any("Cr" in t for t in ticktext)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CHART LINTER & SMART DEFAULTS TESTS
# ─────────────────────────────────────────────────────────────────────────────
class TestChartLinter:
    def test_top_n_plus_other_exact_total_conservation(self):
        """Verify that collapsing >10 categories preserves the exact arithmetic total."""
        categories = [f"Product_{i}" for i in range(50)]
        values = [float(i * 100 + 50) for i in range(50)]
        df = pd.DataFrame({"category": categories, "value": values})
        original_total = df["value"].sum()

        df_clean, lint_res = lint_and_prepare_data(
            df=df, chart_type="bar", x_col="category", y_col="value"
        )

        # Cleaned dataset must have at most 11 categories (top 10 + Other)
        assert len(df_clean) <= 11
        assert "Other" in df_clean["category"].values
        # Strict total conservation check
        assert pytest.approx(df_clean["value"].sum(), 0.001) == original_total
        assert any("top 10" in w for w in lint_res.warnings)

    def test_pie_chart_slice_cap(self):
        """Pie charts must cap slices at 6 and group remainder into Other."""
        slices = [f"Slice_{i}" for i in range(12)]
        vals = [10.0] * 12
        df = pd.DataFrame({"category": slices, "value": vals})
        original_total = df["value"].sum()

        df_clean, lint_res = lint_and_prepare_data(
            df=df, chart_type="pie", x_col="category", y_col="value"
        )
        assert len(df_clean) <= 6
        assert "Other" in df_clean["category"].values
        assert pytest.approx(df_clean["value"].sum(), 0.001) == original_total
        assert any("Recommend bar" in w or "pie slices" in w for w in lint_res.warnings)

    def test_auto_horizontal_flip_rule(self):
        """Horizontal layout triggered if >7 categories or labels >8 characters."""
        # Case A: 8 short categories
        df_a = pd.DataFrame({"category": [f"C{i}" for i in range(8)], "value": range(8)})
        df_clean_a, lint_res_a = lint_and_prepare_data(df_a, "bar", "category", "value")
        assert lint_res_a.is_horizontal is True

        # Case B: 3 long categories (>8 chars)
        df_b = pd.DataFrame({
            "category": ["North America", "Western Europe", "Asia Pacific"],
            "value": [100, 200, 300]
        })
        df_clean_b, lint_res_b = lint_and_prepare_data(df_b, "bar", "category", "value")
        assert lint_res_b.is_horizontal is True

    def test_negative_values_in_composition_blocked(self):
        df_neg = pd.DataFrame({
            "category": ["Alpha", "Beta", "Gamma"],
            "value": [100, -25, 80]
        })
        df_clean, lint_res = lint_and_prepare_data(df_neg, "pie", "category", "value")
        assert any("negative values" in w for w in lint_res.warnings)
        assert (df_clean["value"] >= 0).all()

    def test_line_auto_aggregation_rule(self):
        """Dense time-series (>60 points) re-aggregates to grain yielding <= 60 points."""
        date_rng = pd.date_range("2024-01-01", periods=200, freq="D")
        df_dense = pd.DataFrame({"order_date": date_rng, "value": np.random.randn(200) * 10 + 50})

        df_clean, lint_res = lint_and_prepare_data(df_dense, "line", "order_date", "value")
        assert len(df_clean) <= 60
        assert any("Auto-aggregated" in w for w in lint_res.warnings)

    def test_aria_summary_matches_pandas(self):
        df = pd.DataFrame({
            "region": ["North", "South", "East", "West"],
            "revenue": [5000.0, 2000.0, 1500.0, 1500.0]
        })
        summary = generate_accessible_summary(df, "bar", "region", "revenue", currency="INR")
        assert "revenue by region" in summary.lower()
        assert "North" in summary
        # 5000 / 10000 = 50.0%
        assert "50.0%" in summary


# ─────────────────────────────────────────────────────────────────────────────
# 3. FIGURE BUILDER PRESENTATION DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────
class TestFigurePresentationDefaults:
    def test_no_figure_title_inside_layout(self):
        df = pd.DataFrame({"region": ["A", "B"], "revenue": [100, 200]})
        fig_dict = make_figure(df, chart="bar", x="region", y="revenue", title="Sales by Region")
        layout = fig_dict.get("layout", {})
        # Figure title must be empty or None so card header carries title exclusively
        title_text = layout.get("title", {}).get("text", "")
        assert not title_text or title_text == ""

    def test_zero_baseline_for_bars(self):
        df = pd.DataFrame({"region": ["North", "South"], "revenue": [500, 750]})
        fig_dict = make_figure(df, chart="bar", x="region", y="revenue")
        layout = fig_dict.get("layout", {})
        # Horizontal or vertical bar axis must have rangemode 'tozero'
        xaxis = layout.get("xaxis", {})
        yaxis = layout.get("yaxis", {})
        assert xaxis.get("rangemode") == "tozero" or yaxis.get("rangemode") == "tozero"

    def test_single_series_legend_hidden(self):
        df = pd.DataFrame({"cat": ["A", "B", "C"], "val": [10, 20, 30]})
        fig_dict = make_figure(df, chart="column", x="cat", y="val")
        layout = fig_dict.get("layout", {})
        assert layout.get("showlegend") is False

    def test_multi_series_legend_position(self):
        df = pd.DataFrame({
            "cat": ["A", "A", "B", "B"],
            "val": [10, 20, 30, 40],
            "series": ["S1", "S2", "S1", "S2"]
        })
        fig_dict = make_figure(df, chart="stacked_column", x="cat", y="val", color="series")
        layout = fig_dict.get("layout", {})
        assert layout.get("showlegend") is True
        legend = layout.get("legend", {})
        assert legend.get("orientation") == "h"

    def test_honest_excluded_rows_caption(self):
        # Data with NaN rows
        df = pd.DataFrame({
            "cat": ["A", "B", None, "D", "E"],
            "val": [10, 20, 30, None, 50]
        })
        fig_dict = make_figure(df, chart="bar", x="cat", y="val")
        meta = fig_dict.get("datapilot_meta", {})
        assert meta.get("excluded_count") >= 2
        assert "rows excluded" in meta.get("caption", "").lower()
