"""
Visual Recommender Service for DataPilot.

Profiles columns (role, cardinality, null %, range, skew, rating scales, shares/percents),
excludes PII and ID-like columns, and evaluates rule-based eligibility for all 23 visual types.
Generates ranked recommendations and 6-8 starter visuals for the visual canvas.
"""
from __future__ import annotations

import re
from typing import Any
import numpy as np
import pandas as pd

from .profiling import CURRENCY_CHARS, detect_pii
from .visual_registry import VISUAL_TYPES

# Suffixes and patterns indicating ID or key columns
ID_PATTERNS = re.compile(r"(^id$|_id$|^id_|uuid|guid|code$|key$|order_number)", re.IGNORECASE)
STAGE_PATTERNS = re.compile(r"(stage|status|step|funnel|phase|pipeline)", re.IGNORECASE)
PERCENT_PATTERNS = re.compile(r"(pct|percent|percentage|rate|ratio|share)", re.IGNORECASE)


def profile_columns_for_visuals(df: pd.DataFrame, source_meta: dict | None = None) -> list[dict[str, Any]]:
    """
    Detailed profiling of each column for visualization suitability:
    - role: 'date', 'dimension', 'measure', 'id', 'text', 'boolean', 'pii'
    - cardinality: distinct count
    - null_pct: % missing (0-100)
    - numeric_range: min, max
    - skew: skewness
    - is_rating_scale: bool (integers 1..k with k <= 11)
    - is_percent: bool (values 0..1 or 0..100 with name or share characteristics)
    - can_use_in_visuals: bool (False for PII and ID-like columns)
    - currency_symbol: str | None (detected from source cells or metadata)
    """
    total_rows = len(df)
    profiles = []

    # Check source_meta for detected currencies or PII
    source_currencies = (source_meta or {}).get("column_currencies", {})
    source_pii = (source_meta or {}).get("pii_columns", {})

    for col in df.columns:
        s = df[col]
        non_null = s.dropna()
        n_distinct = int(non_null.nunique())
        null_pct = round(float(s.isna().mean() * 100), 2)
        col_str = str(col).strip()
        col_lower = col_str.lower()

        # 1. PII detection
        pii_type = source_pii.get(col_str)
        if not pii_type and len(non_null) > 0:
            sample_series = non_null.head(100)
            pii_type = detect_pii(sample_series)
        is_pii = bool(pii_type)

        # 2. ID detection
        source_semantics = (source_meta or {}).get("column_semantics", {}) or (source_meta or {}).get("semantics", {})
        col_sem = source_semantics.get(col_str, {})
        is_id = False
        if col_sem.get("semantic_type") == "identifier":
            is_id = True
        elif ID_PATTERNS.search(col_lower):
            is_id = True
        elif total_rows >= 20 and n_distinct == total_rows and not pd.api.types.is_numeric_dtype(s):
            is_id = True

        # 3. Currency symbol inference
        currency_sym = source_currencies.get(col_str)
        if not currency_sym and len(non_null) > 0:
            sample_str = " ".join(non_null.head(50).astype(str))
            for sym in ["₹", "$", "€", "£", "¥"]:
                if sym in sample_str:
                    currency_sym = sym
                    break

        # 4. Role classification
        role = "dimension"
        num_range = None
        skew_val = None
        is_rating_scale = False
        is_percent = False

        if is_pii:
            role = "pii"
        elif is_id:
            role = "id"
        elif pd.api.types.is_datetime64_any_dtype(s) or (
            len(non_null) > 0 and (
                any(w in col_lower for w in ("date", "time", "year", "month", "day", "period"))
                and not pd.api.types.is_numeric_dtype(s)
            )
        ):
            role = "date"
        elif pd.api.types.is_bool_dtype(s) or (
            n_distinct == 2 and set(non_null.astype(str).str.lower().unique()).issubset({"true", "false", "yes", "no", "0", "1"})
        ):
            role = "boolean"
        elif pd.api.types.is_numeric_dtype(s) and not is_id:
            # Check if rating scale (e.g. Likert 1-5, 1-7, 1-10)
            clean_num = pd.to_numeric(non_null, errors="coerce").dropna()
            if not clean_num.empty:
                min_v = float(clean_num.min())
                max_v = float(clean_num.max())
                num_range = {"min": min_v, "max": max_v}
                if len(clean_num) > 2:
                    try:
                        skew_val = round(float(clean_num.skew()), 2)
                    except Exception:
                        skew_val = None

                is_all_ints = (clean_num % 1 == 0).all()
                if is_all_ints and min_v >= 1 and max_v <= 11 and n_distinct <= 11 and n_distinct >= 2:
                    is_rating_scale = True

                if (min_v >= 0 and max_v <= 1.0 and max_v > 0) or (
                    min_v >= 0 and max_v <= 100 and PERCENT_PATTERNS.search(col_lower)
                ):
                    is_percent = True

            role = "measure"
        elif n_distinct > 150 and total_rows > 200:
            role = "text"
        else:
            role = "dimension"

        can_use = not (is_pii or is_id)

        profiles.append({
            "name": col_str,
            "role": role,
            "cardinality": n_distinct,
            "null_pct": null_pct,
            "numeric_range": num_range,
            "skew": skew_val,
            "is_rating_scale": is_rating_scale,
            "is_percent": is_percent,
            "is_pii": is_pii,
            "is_id": is_id,
            "currency_symbol": currency_sym,
            "can_use_in_visuals": can_use,
        })

    return profiles


def evaluate_visual_suitability(
    profiles: list[dict[str, Any]],
    total_rows: int,
    dataset_id: str,
    has_target: bool = False,
) -> dict[str, Any]:
    """
    Evaluates rule-based eligibility for each of the 23 visual types.
    Returns:
    {
      "recommendations": list of {type, suitable, score, reason, default_fields, default_options},
      "starters": list of top 6-8 starter VisualSpec dicts
    }
    """
    usable = [p for p in profiles if p["can_use_in_visuals"]]
    measures = [p for p in usable if p["role"] == "measure"]
    dimensions = [p for p in usable if p["role"] == "dimension"]
    dates = [p for p in usable if p["role"] == "date"]
    rating_scales = [p for p in usable if p["is_rating_scale"]]

    # Primary measure (prefer revenue, sales, amount, total, units, price)
    def measure_priority(p):
        name = p["name"].lower()
        if "revenue" in name or "sales" in name or "amount" in name or "total" in name:
            return 10
        if "units" in name or "qty" in name or "orders" in name:
            return 8
        if "price" in name or "cost" in name:
            return 6
        return 4

    sorted_measures = sorted(measures, key=measure_priority, reverse=True)
    primary_measure = sorted_measures[0]["name"] if sorted_measures else None
    secondary_measure = sorted_measures[1]["name"] if len(sorted_measures) > 1 else None
    third_measure = sorted_measures[2]["name"] if len(sorted_measures) > 2 else None

    # Primary date
    primary_date = dates[0]["name"] if dates else None
    date_periods = dates[0]["cardinality"] if dates else 0

    # Primary dimensions (prefer clean low-moderate cardinality)
    def dim_priority(p):
        card = p["cardinality"]
        if 2 <= card <= 8:
            return 10
        if 9 <= card <= 20:
            return 7
        return 4

    sorted_dims = sorted(dimensions, key=dim_priority, reverse=True)
    primary_dim = sorted_dims[0]["name"] if sorted_dims else None
    primary_dim_card = sorted_dims[0]["cardinality"] if sorted_dims else 0
    secondary_dim = sorted_dims[1]["name"] if len(sorted_dims) > 1 else None

    # Stage dimension for funnel
    stage_dims = [p for p in dimensions if STAGE_PATTERNS.search(p["name"]) and 3 <= p["cardinality"] <= 8]
    funnel_dim = stage_dims[0]["name"] if stage_dims else (sorted_dims[0]["name"] if sorted_dims and 3 <= primary_dim_card <= 8 else None)

    recs = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Line
    # ─────────────────────────────────────────────────────────────────────────
    if primary_date and primary_measure and date_periods >= 6:
        recs.append({
            "type": "line",
            "suitable": True,
            "score": 94,
            "reason": f"{primary_measure} over time: date column '{primary_date}' with {date_periods} distinct periods",
            "default_fields": {"category": primary_date, "value": primary_measure},
            "default_options": {"aggregation": "sum", "date_grain": "month", "sort": "date", "extras": ["trend_line"]},
        })
    else:
        reason = "Requires a date column and a measure column with at least 6 periods"
        if not primary_date:
            reason = "No date column found in dataset"
        elif date_periods < 6:
            reason = f"Date column '{primary_date}' has only {date_periods} periods (minimum 6 required)"
        recs.append({
            "type": "line",
            "suitable": False,
            "score": 10,
            "reason": reason,
            "default_fields": {"category": primary_date or (primary_dim or "category"), "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Area
    # ─────────────────────────────────────────────────────────────────────────
    if primary_date and primary_measure and date_periods >= 6:
        recs.append({
            "type": "area",
            "suitable": True,
            "score": 91,
            "reason": f"Trend volume over time: '{primary_date}' with {date_periods} distinct periods",
            "default_fields": {"category": primary_date, "value": primary_measure},
            "default_options": {"aggregation": "sum", "date_grain": "month", "sort": "date"},
        })
    else:
        recs.append({
            "type": "area",
            "suitable": False,
            "score": 10,
            "reason": "Requires a date column and a measure column with at least 6 periods",
            "default_fields": {"category": primary_date or (primary_dim or "category"), "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Bar (Horizontal)
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and primary_measure and 2 <= primary_dim_card <= 30:
        recs.append({
            "type": "bar",
            "suitable": True,
            "score": 92,
            "reason": f"Compare {primary_measure} across '{primary_dim}' ({primary_dim_card} categories)",
            "default_fields": {"category": primary_dim, "value": primary_measure},
            "default_options": {"aggregation": "sum", "sort": "value_desc", "orientation": "horizontal", "extras": ["value_labels"]},
        })
    else:
        recs.append({
            "type": "bar",
            "suitable": False,
            "score": 20,
            "reason": "Requires a categorical dimension with 2–30 values and a numeric measure",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum", "orientation": "horizontal"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Column (Vertical)
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and primary_measure and 2 <= primary_dim_card <= 30:
        recs.append({
            "type": "column",
            "suitable": True,
            "score": 93,
            "reason": f"Compare {primary_measure} by '{primary_dim}' ({primary_dim_card} categories)",
            "default_fields": {"category": primary_dim, "value": primary_measure},
            "default_options": {"aggregation": "sum", "sort": "value_desc", "orientation": "vertical", "extras": ["value_labels"]},
        })
    else:
        recs.append({
            "type": "column",
            "suitable": False,
            "score": 20,
            "reason": "Requires a categorical dimension with 2–30 values and a numeric measure",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum", "orientation": "vertical"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Stacked Column
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and secondary_dim and primary_measure and 2 <= primary_dim_card <= 15:
        recs.append({
            "type": "stacked_column",
            "suitable": True,
            "score": 85,
            "reason": f"Segmented totals: '{primary_dim}' broken down by '{secondary_dim}'",
            "default_fields": {"category": primary_dim, "value": primary_measure, "colour_by": secondary_dim},
            "default_options": {"aggregation": "sum"},
        })
    else:
        recs.append({
            "type": "stacked_column",
            "suitable": False,
            "score": 25,
            "reason": "Requires two categorical dimensions (2–15 values) and a numeric measure",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value", "colour_by": secondary_dim},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Stacked Bar
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and secondary_dim and primary_measure and 2 <= primary_dim_card <= 15:
        recs.append({
            "type": "stacked_bar",
            "suitable": True,
            "score": 84,
            "reason": f"Horizontal segmented totals: '{primary_dim}' by '{secondary_dim}'",
            "default_fields": {"category": primary_dim, "value": primary_measure, "colour_by": secondary_dim},
            "default_options": {"aggregation": "sum", "orientation": "horizontal"},
        })
    else:
        recs.append({
            "type": "stacked_bar",
            "suitable": False,
            "score": 25,
            "reason": "Requires two categorical dimensions and a numeric measure",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value", "colour_by": secondary_dim},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Combo
    # ─────────────────────────────────────────────────────────────────────────
    if (primary_dim or primary_date) and primary_measure and secondary_measure:
        cat = primary_date or primary_dim
        recs.append({
            "type": "combo",
            "suitable": True,
            "score": 83,
            "reason": f"Dual-metric view: '{primary_measure}' (bars) and '{secondary_measure}' (line) across '{cat}'",
            "default_fields": {"category": cat, "value": primary_measure, "secondary_value": secondary_measure},
            "default_options": {"aggregation": "sum"},
        })
    else:
        recs.append({
            "type": "combo",
            "suitable": False,
            "score": 20,
            "reason": "Requires a dimension or date plus at least two distinct numeric measures",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Pie
    # ─────────────────────────────────────────────────────────────────────────
    # Pick dimension with 2-6 values
    pie_dim_candidates = [p for p in dimensions if 2 <= p["cardinality"] <= 6]
    if pie_dim_candidates and primary_measure:
        p_dim = pie_dim_candidates[0]
        recs.append({
            "type": "pie",
            "suitable": True,
            "score": 87,
            "reason": f"Proportions of {primary_measure} across '{p_dim['name']}' ({p_dim['cardinality']} slices, within 2–6 limit)",
            "default_fields": {"category": p_dim["name"], "value": primary_measure},
            "default_options": {"aggregation": "sum", "legend": "right"},
        })
    else:
        high_card_dim = dimensions[0] if dimensions else None
        reason = "Requires a categorical dimension with 2–6 values and a non-negative measure"
        if high_card_dim and high_card_dim["cardinality"] > 6:
            reason = f"Not recommended: '{high_card_dim['name']}' has {high_card_dim['cardinality']} slices (pie charts with >6 slices clutter and mislead)"
        recs.append({
            "type": "pie",
            "suitable": False,
            "score": 15,
            "reason": reason,
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Donut
    # ─────────────────────────────────────────────────────────────────────────
    if pie_dim_candidates and primary_measure:
        p_dim = pie_dim_candidates[0]
        recs.append({
            "type": "donut",
            "suitable": True,
            "score": 88,
            "reason": f"Share of total {primary_measure} by '{p_dim['name']}' ({p_dim['cardinality']} slices)",
            "default_fields": {"category": p_dim["name"], "value": primary_measure},
            "default_options": {"aggregation": "sum", "legend": "right"},
        })
    else:
        recs.append({
            "type": "donut",
            "suitable": False,
            "score": 15,
            "reason": "Requires a categorical dimension with 2–6 values and a non-negative measure",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Treemap
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and primary_measure and 3 <= primary_dim_card <= 25:
        recs.append({
            "type": "treemap",
            "suitable": True,
            "score": 80,
            "reason": f"Proportional area hierarchy: '{primary_dim}' ({primary_dim_card} categories)",
            "default_fields": {"category": primary_dim, "value": primary_measure},
            "default_options": {"aggregation": "sum"},
        })
    else:
        recs.append({
            "type": "treemap",
            "suitable": False,
            "score": 25,
            "reason": "Requires a categorical dimension with 3–25 values and a non-negative measure",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Funnel
    # ─────────────────────────────────────────────────────────────────────────
    if funnel_dim and primary_measure:
        recs.append({
            "type": "funnel",
            "suitable": True,
            "score": 79,
            "reason": f"Pipeline conversion across stages in '{funnel_dim}'",
            "default_fields": {"category": funnel_dim, "value": primary_measure},
            "default_options": {"aggregation": "sum"},
        })
    else:
        recs.append({
            "type": "funnel",
            "suitable": False,
            "score": 20,
            "reason": "Requires an ordered pipeline/stage dimension with 3–8 values (e.g. stage, status, step)",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 12. Scatter
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure and secondary_measure and total_rows >= 20:
        recs.append({
            "type": "scatter",
            "suitable": True,
            "score": 86,
            "reason": f"Correlation between '{primary_measure}' and '{secondary_measure}' across {total_rows} rows",
            "default_fields": {"x": secondary_measure, "y": primary_measure},
            "default_options": {},
        })
    else:
        recs.append({
            "type": "scatter",
            "suitable": False,
            "score": 15,
            "reason": "Requires at least two distinct numeric measure columns and at least 20 rows",
            "default_fields": {"x": primary_measure or "x", "y": secondary_measure or "y"},
            "default_options": {},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 13. Bubble
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure and secondary_measure and third_measure and total_rows >= 20:
        recs.append({
            "type": "bubble",
            "suitable": True,
            "score": 78,
            "reason": f"3-way metric relationship: '{secondary_measure}' (X), '{primary_measure}' (Y), '{third_measure}' (Size)",
            "default_fields": {"x": secondary_measure, "y": primary_measure, "size": third_measure},
            "default_options": {},
        })
    else:
        recs.append({
            "type": "bubble",
            "suitable": False,
            "score": 10,
            "reason": "Requires three distinct numeric measure columns and at least 20 rows",
            "default_fields": {"x": primary_measure or "x", "y": secondary_measure or "y", "size": third_measure or "size"},
            "default_options": {},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 14. Heatmap
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and secondary_dim and primary_measure and primary_dim_card <= 20:
        recs.append({
            "type": "heatmap",
            "suitable": True,
            "score": 81,
            "reason": f"Cross-dimensional density across '{primary_dim}' and '{secondary_dim}'",
            "default_fields": {"rows": primary_dim, "columns": secondary_dim, "value": primary_measure},
            "default_options": {"aggregation": "sum"},
        })
    else:
        recs.append({
            "type": "heatmap",
            "suitable": False,
            "score": 20,
            "reason": "Requires two categorical dimensions (or date + dimension) with <= 20 values plus a measure",
            "default_fields": {"rows": primary_dim or "rows", "columns": secondary_dim or "columns", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 15. Histogram
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure and total_rows >= 20:
        recs.append({
            "type": "histogram",
            "suitable": True,
            "score": 85,
            "reason": f"Frequency distribution spread of '{primary_measure}' into bins ({total_rows} rows)",
            "default_fields": {"value": primary_measure},
            "default_options": {"histogram_bins": "auto"},
        })
    else:
        recs.append({
            "type": "histogram",
            "suitable": False,
            "score": 15,
            "reason": "Requires a continuous numeric measure column and at least 20 rows",
            "default_fields": {"value": primary_measure or "value"},
            "default_options": {},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 16. Box Plot
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure and total_rows >= 20:
        cat_field = primary_dim if (primary_dim and primary_dim_card <= 10) else None
        reason_txt = f"Quartiles, median & outlier distribution for '{primary_measure}'"
        if cat_field:
            reason_txt += f" grouped by '{cat_field}'"
        recs.append({
            "type": "box",
            "suitable": True,
            "score": 83,
            "reason": reason_txt,
            "default_fields": {"value": primary_measure, **({"category": cat_field} if cat_field else {})},
            "default_options": {},
        })
    else:
        recs.append({
            "type": "box",
            "suitable": False,
            "score": 15,
            "reason": "Requires a continuous numeric measure column and at least 20 rows",
            "default_fields": {"value": primary_measure or "value"},
            "default_options": {},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 17. Likert Stack
    # ─────────────────────────────────────────────────────────────────────────
    if len(rating_scales) >= 2:
        recs.append({
            "type": "likert_stack",
            "suitable": True,
            "score": 89,
            "reason": f"Survey battery: {len(rating_scales)} rating-scale columns detected ({', '.join(p['name'] for p in rating_scales[:3])})",
            "default_fields": {"category": rating_scales[0]["name"], "value": rating_scales[1]["name"]},
            "default_options": {"likert_scale": "1-5"},
        })
    else:
        recs.append({
            "type": "likert_stack",
            "suitable": False,
            "score": 5,
            "reason": "Requires at least two rating-scale survey columns (integer ratings 1..k with k <= 11)",
            "default_fields": {"category": primary_dim or "category", "value": primary_measure or "value"},
            "default_options": {},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 18. Gauge
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure and has_target:
        recs.append({
            "type": "gauge",
            "suitable": True,
            "score": 82,
            "reason": f"Progress toward target goal for '{primary_measure}'",
            "default_fields": {"value": primary_measure},
            "default_options": {"aggregation": "sum", "compare_to": "target"},
        })
    else:
        recs.append({
            "type": "gauge",
            "suitable": False,
            "score": 25,
            "reason": "Requires a benchmark target value (e.g. from a Targets sheet or user goal)",
            "default_fields": {"value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 19. Bullet Bar
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure and has_target:
        recs.append({
            "type": "bullet",
            "suitable": True,
            "score": 81,
            "reason": f"Performance vs benchmark target for '{primary_measure}'",
            "default_fields": {"value": primary_measure},
            "default_options": {"aggregation": "sum", "compare_to": "target"},
        })
    else:
        recs.append({
            "type": "bullet",
            "suitable": False,
            "score": 25,
            "reason": "Requires a benchmark target value to compare against",
            "default_fields": {"value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 20. KPI Card
    # ─────────────────────────────────────────────────────────────────────────
    if primary_measure:
        currency_sym = next((p["currency_symbol"] for p in measures if p["currency_symbol"]), None)
        fmt = "currency_inr" if currency_sym == "₹" else ("auto" if currency_sym else "integer")
        recs.append({
            "type": "kpi_card",
            "suitable": True,
            "score": 96,
            "reason": f"Headline total for key metric '{primary_measure}'",
            "default_fields": {"value": primary_measure},
            "default_options": {"aggregation": "sum", "number_format": fmt},
        })
    else:
        recs.append({
            "type": "kpi_card",
            "suitable": False,
            "score": 20,
            "reason": "Requires at least one numeric measure column",
            "default_fields": {"value": "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 21. Sparkline KPI
    # ─────────────────────────────────────────────────────────────────────────
    if primary_date and primary_measure and date_periods >= 6:
        recs.append({
            "type": "sparkline_kpi",
            "suitable": True,
            "score": 90,
            "reason": f"Headline '{primary_measure}' with historical 12-month trendline",
            "default_fields": {"category": primary_date, "value": primary_measure},
            "default_options": {"aggregation": "sum", "date_grain": "month"},
        })
    else:
        recs.append({
            "type": "sparkline_kpi",
            "suitable": False,
            "score": 15,
            "reason": "Requires a date column and a measure column with at least 6 periods",
            "default_fields": {"category": primary_date or "category", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 22. Table
    # ─────────────────────────────────────────────────────────────────────────
    # Tables are always allowed
    recs.append({
        "type": "table",
        "suitable": True,
        "score": 75,
        "reason": "Tabular raw or grouped record view with sorting and pagination",
        "default_fields": {"columns": [p["name"] for p in usable[:6]]},
        "default_options": {},
    })

    # ─────────────────────────────────────────────────────────────────────────
    # 23. Pivot
    # ─────────────────────────────────────────────────────────────────────────
    if primary_dim and primary_measure:
        recs.append({
            "type": "pivot",
            "suitable": True,
            "score": 78,
            "reason": f"Multi-axis cross-tabulation of '{primary_measure}' by '{primary_dim}'",
            "default_fields": {"rows": primary_dim, "columns": secondary_dim or primary_dim, "value": primary_measure},
            "default_options": {"aggregation": "sum"},
        })
    else:
        recs.append({
            "type": "pivot",
            "suitable": False,
            "score": 20,
            "reason": "Requires at least one categorical dimension and one numeric measure",
            "default_fields": {"rows": primary_dim or "rows", "columns": secondary_dim or "columns", "value": primary_measure or "value"},
            "default_options": {"aggregation": "sum"},
        })

    # Sort recommendations by suitability (True first) then by score descending
    recs_sorted = sorted(recs, key=lambda r: (1 if r["suitable"] else 0, r["score"]), reverse=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Build 6-8 Starter Visuals from the top suitable visuals
    # ─────────────────────────────────────────────────────────────────────────
    starters = []
    suitable_recs = [r for r in recs_sorted if r["suitable"]]

    # 1. Primary KPI card (Total / Sum)
    if primary_measure:
        m_prof = next((p for p in measures if p["name"] == primary_measure), None)
        currency_sym = m_prof.get("currency_symbol") if m_prof else None
        fmt = "currency_inr" if currency_sym == "₹" else ("auto" if currency_sym else "integer")
        starters.append({
            "id": f"start_kpi_{len(starters)+1}",
            "type": "kpi_card",
            "title": f"Total {primary_measure.replace('_', ' ').title()}",
            "dataset_id": dataset_id,
            "fields": {"value": primary_measure},
            "options": {"aggregation": "sum", "number_format": fmt},
            "suitability_reason": f"Headline sum for key metric '{primary_measure}'",
        })

    # 2. Count / Volume KPI (e.g. Total Records or Orders)
    count_col = usable[0]["name"] if usable else (primary_measure or "value")
    starters.append({
        "id": f"start_kpi_{len(starters)+1}",
        "type": "kpi_card",
        "title": "Total Records",
        "dataset_id": dataset_id,
        "fields": {"value": count_col},
        "options": {"aggregation": "count", "number_format": "integer"},
        "suitability_reason": "Total row count of the active dataset",
    })

    # 3. Average KPI or Secondary Measure KPI
    avg_measure = secondary_measure or primary_measure
    if avg_measure:
        m_prof = next((p for p in measures if p["name"] == avg_measure), None)
        currency_sym = m_prof.get("currency_symbol") if m_prof else None
        fmt = "currency_inr" if currency_sym == "₹" else "auto"
        starters.append({
            "id": f"start_kpi_{len(starters)+1}",
            "type": "kpi_card",
            "title": f"Average {avg_measure.replace('_', ' ').title()}",
            "dataset_id": dataset_id,
            "fields": {"value": avg_measure},
            "options": {"aggregation": "average", "number_format": fmt},
            "suitability_reason": f"Mean value benchmark for '{avg_measure}'",
        })

    # 4. Trend Chart (Line or Area if suitable)
    line_rec = next((r for r in suitable_recs if r["type"] == "line"), None)
    area_rec = next((r for r in suitable_recs if r["type"] == "area"), None)
    trend_rec = line_rec or area_rec
    if trend_rec:
        starters.append({
            "id": f"start_chart_{len(starters)+1}",
            "type": trend_rec["type"],
            "title": f"{primary_measure.replace('_', ' ').title()} Over Time",
            "dataset_id": dataset_id,
            "fields": dict(trend_rec["default_fields"]),
            "options": dict(trend_rec["default_options"]),
            "suitability_reason": trend_rec["reason"],
        })

    # 5. Category Comparison (Bar or Column)
    bar_rec = next((r for r in suitable_recs if r["type"] in ("column", "bar")), None)
    if bar_rec:
        cat_name = bar_rec["default_fields"].get("category", "")
        starters.append({
            "id": f"start_chart_{len(starters)+1}",
            "type": bar_rec["type"],
            "title": f"{primary_measure.replace('_', ' ').title()} by {cat_name.replace('_', ' ').title()}",
            "dataset_id": dataset_id,
            "fields": dict(bar_rec["default_fields"]),
            "options": dict(bar_rec["default_options"]),
            "suitability_reason": bar_rec["reason"],
        })

    # 6. Part-to-whole (Donut or Pie) if suitable
    donut_rec = next((r for r in suitable_recs if r["type"] in ("donut", "pie")), None)
    if donut_rec:
        cat_name = donut_rec["default_fields"].get("category", "")
        starters.append({
            "id": f"start_chart_{len(starters)+1}",
            "type": donut_rec["type"],
            "title": f"Share of {primary_measure.replace('_', ' ').title()} by {cat_name.replace('_', ' ').title()}",
            "dataset_id": dataset_id,
            "fields": dict(donut_rec["default_fields"]),
            "options": dict(donut_rec["default_options"]),
            "suitability_reason": donut_rec["reason"],
        })

    # 7. Distribution or Relationship or Survey (Histogram / Scatter / Likert)
    other_types = ["likert_stack", "scatter", "histogram", "box", "table"]
    for ot in other_types:
        if len(starters) >= 8:
            break
        ot_rec = next((r for r in suitable_recs if r["type"] == ot), None)
        if ot_rec and not any(s["type"] == ot for s in starters):
            title = f"{ot_rec['type'].replace('_', ' ').title()}"
            if ot == "histogram":
                title = f"Distribution of {primary_measure.replace('_', ' ').title()}"
            elif ot == "scatter":
                title = f"{primary_measure.replace('_', ' ').title()} vs {secondary_measure.replace('_', ' ').title()}"
            elif ot == "likert_stack":
                title = "Survey Rating Breakdown"
            starters.append({
                "id": f"start_chart_{len(starters)+1}",
                "type": ot_rec["type"],
                "title": title,
                "dataset_id": dataset_id,
                "fields": dict(ot_rec["default_fields"]),
                "options": dict(ot_rec["default_options"]),
                "suitability_reason": ot_rec["reason"],
            })

    return {
        "columns_profile": profiles,
        "recommendations": recs_sorted,
        "starters": starters[:8],
    }
