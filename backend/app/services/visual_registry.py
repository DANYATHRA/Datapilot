"""
Visual Studio Registry — Single Source of Truth for DataPilot.

Defines all 23 visual types, categories, fixed dropdown options,
and the per-visual applicable options matrix.
Exposed via GET /visuals/registry.
"""
from __future__ import annotations
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# 23 VISUAL TYPES WITH METADATA
# ─────────────────────────────────────────────────────────────────────────────
VISUAL_CATEGORIES = [
    {"id": "all", "label": "All"},
    {"id": "kpi", "label": "Key numbers"},
    {"id": "compare", "label": "Compare"},
    {"id": "trend", "label": "Trend"},
    {"id": "composition", "label": "Parts of a whole"},
    {"id": "relationship", "label": "Relationship"},
    {"id": "distribution", "label": "Distribution"},
    {"id": "tables", "label": "Tables"},
]

VISUAL_TYPES: dict[str, dict[str, Any]] = {
    # ── Key numbers (4)
    "kpi_card": {
        "id": "kpi_card",
        "name": "KPI card",
        "category": "kpi",
        "icon": "TrendingUp",
        "best_for": "Single headline number with comparison to previous period, target, or YoY.",
    },
    "sparkline_kpi": {
        "id": "sparkline_kpi",
        "name": "Sparkline KPI",
        "category": "kpi",
        "icon": "Activity",
        "best_for": "Headline metric with mini 12-point trendline over time.",
    },
    "gauge": {
        "id": "gauge",
        "name": "Gauge",
        "category": "kpi",
        "icon": "Gauge",
        "best_for": "Progress toward a target, SLA score, or data quality index (0–100%).",
    },
    "bullet": {
        "id": "bullet",
        "name": "Bullet bar",
        "category": "kpi",
        "icon": "Target",
        "best_for": "Compare a metric against a target threshold in a compact horizontal bar.",
    },

    # ── Compare (4)
    "column": {
        "id": "column",
        "name": "Column",
        "category": "compare",
        "icon": "ChartColumn",
        "best_for": "Compare values across distinct categories or time periods vertically.",
    },
    "bar": {
        "id": "bar",
        "name": "Bar",
        "category": "compare",
        "icon": "BarChartHorizontal",
        "best_for": "Compare categories with longer labels horizontally.",
    },
    "stacked_column": {
        "id": "stacked_column",
        "name": "Stacked column",
        "category": "compare",
        "icon": "Layers",
        "best_for": "Compare totals and sub-segment contributions across categories.",
    },
    "combo": {
        "id": "combo",
        "name": "Combo",
        "category": "compare",
        "icon": "GitMerge",
        "best_for": "Bars for primary volume plus a trend line for secondary rate or percentage.",
    },

    # ── Trend (2)
    "line": {
        "id": "line",
        "name": "Line",
        "category": "trend",
        "icon": "LineChart",
        "best_for": "Track continuous progression, seasonality, and change over time.",
    },
    "area": {
        "id": "area",
        "name": "Area",
        "category": "trend",
        "icon": "AreaChart",
        "best_for": "Trend with volume or cumulative magnitude filled under the curve.",
    },

    # ── Parts of a whole (4)
    "pie": {
        "id": "pie",
        "name": "Pie",
        "category": "composition",
        "icon": "PieChart",
        "best_for": "Proportions that add up to 100% across 2–6 distinct slices.",
    },
    "donut": {
        "id": "donut",
        "name": "Donut",
        "category": "composition",
        "icon": "CircleDot",
        "best_for": "Modern proportion breakdown with center KPI or total value.",
    },
    "treemap": {
        "id": "treemap",
        "name": "Treemap",
        "category": "composition",
        "icon": "Grid",
        "best_for": "Nested proportional hierarchy displayed as nested rectangles.",
    },
    "funnel": {
        "id": "funnel",
        "name": "Funnel",
        "category": "composition",
        "icon": "Filter",
        "best_for": "Conversion stages, attrition rates, and pipeline progression.",
    },

    # ── Relationship (3)
    "scatter": {
        "id": "scatter",
        "name": "Scatter",
        "category": "relationship",
        "icon": "ScatterChart",
        "best_for": "Two continuous variables to uncover correlation, clustering, and outliers.",
    },
    "bubble": {
        "id": "bubble",
        "name": "Bubble",
        "category": "relationship",
        "icon": "Circle",
        "best_for": "Three continuous variables: X-axis, Y-axis, and bubble area size.",
    },
    "heatmap": {
        "id": "heatmap",
        "name": "Heatmap",
        "category": "relationship",
        "icon": "Grid3X3",
        "best_for": "Intensity matrix across two dimensions (e.g. Day of Week × Hour).",
    },

    # ── Distribution (2)
    "histogram": {
        "id": "histogram",
        "name": "Histogram",
        "category": "distribution",
        "icon": "BarChart2",
        "best_for": "Frequency distribution and skewness of a numeric column into bins.",
    },
    "box": {
        "id": "box",
        "name": "Box plot",
        "category": "distribution",
        "icon": "Box",
        "best_for": "Median, quartiles, spread, and outlier points per group.",
    },

    # ── Tables & Surveys (4)
    "table": {
        "id": "table",
        "name": "Table",
        "category": "tables",
        "icon": "Table",
        "best_for": "Raw records or grouped summaries with pagination, sorting, and totals.",
    },
    "pivot": {
        "id": "pivot",
        "name": "Pivot",
        "category": "tables",
        "icon": "Columns",
        "best_for": "Cross-tabulation with row groupings, column headers, and aggregate cells.",
    },
    "likert_stack": {
        "id": "likert_stack",
        "name": "Likert stack",
        "category": "tables",
        "icon": "SlidersHorizontal",
        "best_for": "Survey Likert ratings diverging stacked bar (Strongly Disagree to Strongly Agree).",
    },
    "stacked_bar": {
        "id": "stacked_bar",
        "name": "Stacked bar",
        "category": "compare",
        "icon": "AlignLeft",
        "best_for": "Horizontal stacked breakdown across multiple sub-segments.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# FIXED DROPDOWNS AND OPTIONS (SINGLE SOURCE OF TRUTH)
# ─────────────────────────────────────────────────────────────────────────────
DROPDOWN_OPTIONS: dict[str, list[dict[str, str]]] = {
    "aggregation": [
        {"value": "sum", "label": "Sum"},
        {"value": "average", "label": "Average"},
        {"value": "count", "label": "Count"},
        {"value": "distinct_count", "label": "Distinct count"},
        {"value": "median", "label": "Median"},
        {"value": "min", "label": "Min"},
        {"value": "max", "label": "Max"},
        {"value": "pct_of_total", "label": "% of total"},
        {"value": "running_total", "label": "Running total"},
    ],
    "date_grain": [
        {"value": "day", "label": "Day"},
        {"value": "week", "label": "Week"},
        {"value": "month", "label": "Month"},
        {"value": "quarter", "label": "Quarter"},
        {"value": "year", "label": "Year"},
        {"value": "weekday", "label": "Weekday"},
        {"value": "hour", "label": "Hour"},
    ],
    "compare_to": [
        {"value": "none", "label": "None"},
        {"value": "previous_period", "label": "Previous period"},
        {"value": "same_period_last_year", "label": "Same period last year"},
        {"value": "target", "label": "Target value"},
        {"value": "column_average", "label": "Column average"},
    ],
    "sort": [
        {"value": "value_desc", "label": "Value ↓ (Highest first)"},
        {"value": "value_asc", "label": "Value ↑ (Lowest first)"},
        {"value": "label_asc", "label": "Label A → Z"},
        {"value": "label_desc", "label": "Label Z → A"},
        {"value": "date", "label": "Date order"},
        {"value": "original", "label": "Original order"},
    ],
    "show": [
        {"value": "all", "label": "All"},
        {"value": "top_5", "label": "Top 5"},
        {"value": "top_10", "label": "Top 10"},
        {"value": "top_20", "label": "Top 20"},
        {"value": "bottom_5", "label": "Bottom 5"},
        {"value": "bottom_10", "label": "Bottom 10"},
    ],
    "number_format": [
        {"value": "auto", "label": "Auto"},
        {"value": "integer", "label": "Integer (1,234)"},
        {"value": "currency_inr", "label": "Currency INR (₹1,234.56)"},
        {"value": "currency_inr_compact", "label": "Compact INR (₹21.2L)"},
        {"value": "percent", "label": "Percent (12.4%)"},
        {"value": "decimal_2", "label": "Decimal 2 places (12.34)"},
        {"value": "date", "label": "Date (YYYY-MM-DD)"},
    ],
    "palette": [
        {"value": "teal", "label": "Teal & Emerald (DataPilot)"},
        {"value": "ocean", "label": "Ocean Blue"},
        {"value": "sunset", "label": "Sunset Orange"},
        {"value": "colour_blind_safe", "label": "Color-blind safe"},
        {"value": "greys", "label": "Monochrome greys"},
        {"value": "custom", "label": "Custom"},
    ],
    "legend": [
        {"value": "right", "label": "Right"},
        {"value": "bottom", "label": "Bottom"},
        {"value": "top", "label": "Top"},
        {"value": "hidden", "label": "Hidden"},
    ],
    "orientation": [
        {"value": "vertical", "label": "Vertical"},
        {"value": "horizontal", "label": "Horizontal"},
    ],
    "missing_values": [
        {"value": "ignore", "label": "Ignore / Skip"},
        {"value": "zero", "label": "Treat as zero"},
        {"value": "gaps", "label": "Show as gaps"},
        {"value": "connect", "label": "Connect lines across gaps"},
    ],
    "filter_operator": [
        {"value": "is", "label": "Is (equals)"},
        {"value": "is_not", "label": "Is not"},
        {"value": "contains", "label": "Contains"},
        {"value": "gt", "label": "Greater than (>)"},
        {"value": "lt", "label": "Less than (<)"},
        {"value": "between", "label": "Between"},
        {"value": "is_empty", "label": "Is empty / null"},
        {"value": "is_not_empty", "label": "Is not empty"},
        {"value": "top_n", "label": "In Top N"},
    ],
    "date_range": [
        {"value": "all_time", "label": "All time"},
        {"value": "last_30_days", "label": "Last 30 days"},
        {"value": "last_90_days", "label": "Last 90 days"},
        {"value": "this_year", "label": "This year"},
        {"value": "last_year", "label": "Last year"},
        {"value": "custom", "label": "Custom date range"},
    ],
    "histogram_bins": [
        {"value": "auto", "label": "Auto"},
        {"value": "5", "label": "5 bins"},
        {"value": "10", "label": "10 bins"},
        {"value": "20", "label": "20 bins"},
        {"value": "50", "label": "50 bins"},
        {"value": "custom", "label": "Custom bin count"},
    ],
    "likert_scale": [
        {"value": "1-5", "label": "1–5 Scale (Strongly Disagree to Strongly Agree)"},
        {"value": "1-7", "label": "1–7 Scale"},
        {"value": "1-10", "label": "1–10 Scale (NPS style)"},
        {"value": "top2box", "label": "Top-2 Box %"},
        {"value": "bottom2box", "label": "Bottom-2 Box %"},
        {"value": "mean", "label": "Mean Score"},
    ],
    "extras": [
        {"value": "value_labels", "label": "Show value labels on data points"},
        {"value": "average_line", "label": "Show column average benchmark line"},
        {"value": "trend_line", "label": "Show linear trendline"},
        {"value": "highlight_outliers", "label": "Highlight detected outliers"},
        {"value": "mark_change_points", "label": "Mark detected change points"},
        {"value": "show_table", "label": "Show underlying data table"},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# PER-VISUAL APPLICABLE OPTIONS MATRIX
# Controls which dropdowns each visual shows on the frontend & validates on backend.
# ─────────────────────────────────────────────────────────────────────────────
APPLICABLE_OPTIONS_MATRIX: dict[str, dict[str, Any]] = {
    "kpi_card": {
        "required_fields": ["value"],
        "optional_fields": ["date_field"],
        "field_roles": {"value": ["measure"], "date_field": ["date"]},
        "allowed_options": ["aggregation", "date_grain", "compare_to", "number_format", "target"],
    },
    "sparkline_kpi": {
        "required_fields": ["value", "category"],
        "optional_fields": [],
        "field_roles": {"value": ["measure"], "category": ["date"]},
        "allowed_options": ["aggregation", "date_grain", "compare_to", "number_format", "target", "palette"],
    },
    "gauge": {
        "required_fields": ["value"],
        "optional_fields": [],
        "field_roles": {"value": ["measure"]},
        "allowed_options": ["aggregation", "target", "number_format", "palette"],
    },
    "bullet": {
        "required_fields": ["value"],
        "optional_fields": ["category"],
        "field_roles": {"value": ["measure"], "category": ["dimension", "date"]},
        "allowed_options": ["aggregation", "target", "number_format", "orientation", "palette"],
    },
    "column": {
        "required_fields": ["category", "value"],
        "optional_fields": ["colour_by"],
        "field_roles": {"category": ["dimension", "date"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format", "legend", "palette", "extras"],
    },
    "bar": {
        "required_fields": ["category", "value"],
        "optional_fields": ["colour_by"],
        "field_roles": {"category": ["dimension", "date"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "sort", "show", "orientation", "number_format", "legend", "palette", "extras"],
    },
    "stacked_column": {
        "required_fields": ["category", "value", "colour_by"],
        "optional_fields": [],
        "field_roles": {"category": ["dimension", "date"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format", "legend", "palette", "extras"],
    },
    "stacked_bar": {
        "required_fields": ["category", "value", "colour_by"],
        "optional_fields": [],
        "field_roles": {"category": ["dimension", "date"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "sort", "show", "orientation", "number_format", "legend", "palette", "extras"],
    },
    "combo": {
        "required_fields": ["category", "value"],
        "optional_fields": ["secondary_value", "colour_by"],
        "field_roles": {"category": ["dimension", "date"], "value": ["measure"], "secondary_value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format", "legend", "palette", "extras"],
    },
    "line": {
        "required_fields": ["category", "value"],
        "optional_fields": ["colour_by"],
        "field_roles": {"category": ["date", "dimension"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "date_grain", "compare_to", "number_format", "legend", "palette", "missing_values", "extras"],
    },
    "area": {
        "required_fields": ["category", "value"],
        "optional_fields": ["colour_by"],
        "field_roles": {"category": ["date", "dimension"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["aggregation", "date_grain", "compare_to", "number_format", "legend", "palette", "missing_values", "extras"],
    },
    "pie": {
        "required_fields": ["category", "value"],
        "optional_fields": [],
        "field_roles": {"category": ["dimension"], "value": ["measure"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format", "legend", "palette"],
    },
    "donut": {
        "required_fields": ["category", "value"],
        "optional_fields": [],
        "field_roles": {"category": ["dimension"], "value": ["measure"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format", "legend", "palette"],
    },
    "treemap": {
        "required_fields": ["category", "value"],
        "optional_fields": ["sub_category"],
        "field_roles": {"category": ["dimension"], "sub_category": ["dimension"], "value": ["measure"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format", "palette"],
    },
    "funnel": {
        "required_fields": ["category", "value"],
        "optional_fields": [],
        "field_roles": {"category": ["dimension"], "value": ["measure"]},
        "allowed_options": ["aggregation", "sort", "number_format", "palette"],
    },
    "scatter": {
        "required_fields": ["x", "y"],
        "optional_fields": ["colour_by"],
        "field_roles": {"x": ["measure", "date"], "y": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["number_format", "legend", "palette", "extras"],
    },
    "bubble": {
        "required_fields": ["x", "y", "size"],
        "optional_fields": ["colour_by"],
        "field_roles": {"x": ["measure", "date"], "y": ["measure"], "size": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["number_format", "legend", "palette"],
    },
    "heatmap": {
        "required_fields": ["rows", "columns", "value"],
        "optional_fields": [],
        "field_roles": {"rows": ["dimension", "date"], "columns": ["dimension", "date"], "value": ["measure"]},
        "allowed_options": ["aggregation", "date_grain", "number_format", "palette"],
    },
    "histogram": {
        "required_fields": ["value"],
        "optional_fields": ["colour_by"],
        "field_roles": {"value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["histogram_bins", "palette", "number_format"],
    },
    "box": {
        "required_fields": ["value"],
        "optional_fields": ["category", "colour_by"],
        "field_roles": {"value": ["measure"], "category": ["dimension"], "colour_by": ["dimension"]},
        "allowed_options": ["number_format", "palette"],
    },
    "table": {
        "required_fields": ["columns"],
        "optional_fields": [],
        "field_roles": {"columns": ["dimension", "measure", "date"]},
        "allowed_options": ["aggregation", "sort", "show", "number_format"],
    },
    "pivot": {
        "required_fields": ["rows", "columns", "value"],
        "optional_fields": [],
        "field_roles": {"rows": ["dimension"], "columns": ["dimension", "date"], "value": ["measure"]},
        "allowed_options": ["aggregation", "date_grain", "number_format"],
    },
    "likert_stack": {
        "required_fields": ["category", "value"],
        "optional_fields": ["colour_by"],
        "field_roles": {"category": ["dimension"], "value": ["measure"], "colour_by": ["dimension"]},
        "allowed_options": ["likert_scale", "palette", "legend"],
    },
}


def get_visual_registry() -> dict[str, Any]:
    """Exposed at GET /visuals/registry for the frontend single source of truth."""
    return {
        "visual_types": list(VISUAL_TYPES.values()),
        "categories": VISUAL_CATEGORIES,
        "options": DROPDOWN_OPTIONS,
        "matrix": APPLICABLE_OPTIONS_MATRIX,
        "defaults": {
            "palette": "teal",
            "legend": "right",
            "orientation": "vertical",
            "aggregation": "sum",
            "date_grain": "month",
            "compare_to": "none",
            "sort": "value_desc",
            "show": "all",
            "number_format": "auto",
            "missing_values": "ignore",
            "histogram_bins": "auto",
            "likert_scale": "1-5",
        },
    }
