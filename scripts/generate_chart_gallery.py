"""
Generate DataPilot Chart Gallery for all 23 Visual Types + Stress Cases.

Renders high-resolution PNGs at small (360px), medium (640px), and large (1000px)
for sample_data/datapilot_test_sales.xlsx after automated cleaning.
Saves all visual artifacts to docs/chart-gallery/.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from backend.app.services.pipeline import run_pipeline
from backend.app.services import charts

GALLERY_DIR = ROOT / "docs" / "chart-gallery"
GALLERY_DIR.mkdir(parents=True, exist_ok=True)

SIZES = [
    ("small", 360, 320),
    ("medium", 640, 320),
    ("large", 1000, 360),
]

WIDE_SIZES = [
    ("small", 360, 320),
    ("medium", 640, 400),
    ("large", 1000, 400),
]


def load_cleaned_sales_data() -> pd.DataFrame:
    raw_path = ROOT / "sample_data" / "datapilot_test_sales.xlsx"
    raw_df = pd.read_excel(raw_path)
    res = run_pipeline(raw_df)
    cleaned = res["cleaned_df"].copy()
    cleaned["order_date"] = pd.to_datetime(cleaned["order_date"])
    return cleaned


def export_figure(fig_dict: dict, name: str, is_wide: bool = False) -> list[str]:
    """Export a figure dictionary to PNG at small, medium, and large sizes."""
    fig = go.Figure(fig_dict)
    size_specs = WIDE_SIZES if is_wide else SIZES
    saved_paths = []

    for label, w, h in size_specs:
        out_file = GALLERY_DIR / f"{name}_{label}_{w}x{h}.png"
        img_bytes = fig.to_image(format="png", width=w, height=h, scale=2)
        out_file.write_bytes(img_bytes)
        saved_paths.append(str(out_file))

    return saved_paths


def main():
    print(f"Loading and cleaning test sales data...")
    df = load_cleaned_sales_data()
    print(f"Cleaned dataset loaded: {len(df)} rows, {len(df.columns)} columns.")

    gallery_index = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. KPI CARD
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [1/23] kpi_card...")
    df_kpi = pd.DataFrame([{"metric": "Total Revenue", "value": df["revenue"].sum()}])
    fig_kpi = charts.make_figure(df_kpi, chart="kpi_card", x="metric", y="value", currency="INR")
    paths = export_figure(fig_kpi, "01_kpi_card")
    gallery_index.append({"id": "kpi_card", "paths": paths, "meta": fig_kpi.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 2. SPARKLINE KPI
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [2/23] sparkline_kpi...")
    df_spark = df.groupby(pd.Grouper(key="order_date", freq="M"))["revenue"].sum().reset_index()
    df_spark.columns = ["period", "value"]
    fig_spark = charts.make_figure(df_spark, chart="sparkline_kpi", x="period", y="value", currency="INR")
    paths = export_figure(fig_spark, "02_sparkline_kpi")
    gallery_index.append({"id": "sparkline_kpi", "paths": paths, "meta": fig_spark.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 3. GAUGE
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [3/23] gauge...")
    # Target achievement % (84% of quarterly quota)
    df_gauge = pd.DataFrame([{"metric": "Quota Attainment", "value": 84.5}])
    fig_gauge = charts.make_figure(df_gauge, chart="gauge", x="metric", y="value")
    paths = export_figure(fig_gauge, "03_gauge")
    gallery_index.append({"id": "gauge", "paths": paths, "meta": fig_gauge.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 4. BULLET
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [4/23] bullet...")
    df_bullet = pd.DataFrame([{"metric": "Revenue Target", "value": 7800000}])
    fig_bullet = charts.make_figure(df_bullet, chart="bullet", x="metric", y="value", currency="INR")
    paths = export_figure(fig_bullet, "04_bullet")
    gallery_index.append({"id": "bullet", "paths": paths, "meta": fig_bullet.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 5. COLUMN
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [5/23] column...")
    df_col = df.groupby("region")["revenue"].sum().reset_index()
    fig_col = charts.make_figure(
        df_col, chart="column", x="region", y="revenue",
        currency="INR", options={"extras": ["value_labels"]}
    )
    paths = export_figure(fig_col, "05_column")
    gallery_index.append({"id": "column", "paths": paths, "meta": fig_col.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 6. BAR (Horizontal bar with product names)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [6/23] bar...")
    df_bar = df.groupby("product")["revenue"].sum().reset_index()
    fig_bar = charts.make_figure(
        df_bar, chart="bar", x="product", y="revenue",
        currency="INR", options={"extras": ["value_labels"]}
    )
    paths = export_figure(fig_bar, "06_bar")
    gallery_index.append({"id": "bar", "paths": paths, "meta": fig_bar.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 7. STACKED COLUMN
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [7/23] stacked_column...")
    df_scol = df.groupby(["region", "product"])["revenue"].sum().reset_index()
    fig_scol = charts.make_figure(
        df_scol, chart="stacked_column", x="region", y="revenue", color="product",
        currency="INR"
    )
    paths = export_figure(fig_scol, "07_stacked_column", is_wide=True)
    gallery_index.append({"id": "stacked_column", "paths": paths, "meta": fig_scol.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 8. STACKED BAR
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [8/23] stacked_bar...")
    df_sbar = df.groupby(["product", "region"])["revenue"].sum().reset_index()
    fig_sbar = charts.make_figure(
        df_sbar, chart="stacked_bar", x="product", y="revenue", color="region",
        currency="INR"
    )
    paths = export_figure(fig_sbar, "08_stacked_bar", is_wide=True)
    gallery_index.append({"id": "stacked_bar", "paths": paths, "meta": fig_sbar.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 9. COMBO
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [9/23] combo...")
    df_combo = df.groupby(pd.Grouper(key="order_date", freq="M")).agg({
        "revenue": "sum",
        "satisfaction_rating": "mean"
    }).reset_index()
    df_combo.columns = ["period", "revenue", "rating"]
    fig_combo = charts.make_figure(
        df_combo, chart="combo", x="period", y="revenue", color="rating",
        currency="INR"
    )
    paths = export_figure(fig_combo, "09_combo", is_wide=True)
    gallery_index.append({"id": "combo", "paths": paths, "meta": fig_combo.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 10. LINE
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [10/23] line...")
    df_line = df.groupby(pd.Grouper(key="order_date", freq="W"))["revenue"].sum().reset_index()
    fig_line = charts.make_figure(
        df_line, chart="line", x="order_date", y="revenue",
        currency="INR", options={"extras": ["average_line"]}
    )
    paths = export_figure(fig_line, "10_line", is_wide=True)
    gallery_index.append({"id": "line", "paths": paths, "meta": fig_line.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 11. AREA
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [11/23] area...")
    df_area = df.groupby(pd.Grouper(key="order_date", freq="M"))["revenue"].sum().reset_index()
    fig_area = charts.make_figure(
        df_area, chart="area", x="order_date", y="revenue",
        currency="INR"
    )
    paths = export_figure(fig_area, "11_area", is_wide=True)
    gallery_index.append({"id": "area", "paths": paths, "meta": fig_area.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 12. PIE (<=6 slices)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [12/23] pie...")
    df_pie = df.groupby("region")["revenue"].sum().reset_index()
    fig_pie = charts.make_figure(df_pie, chart="pie", x="region", y="revenue", currency="INR")
    paths = export_figure(fig_pie, "12_pie")
    gallery_index.append({"id": "pie", "paths": paths, "meta": fig_pie.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 13. DONUT (Center total & outside labels)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [13/23] donut...")
    df_donut = df.groupby("region")["revenue"].sum().reset_index()
    fig_donut = charts.make_figure(df_donut, chart="donut", x="region", y="revenue", currency="INR")
    paths = export_figure(fig_donut, "13_donut")
    gallery_index.append({"id": "donut", "paths": paths, "meta": fig_donut.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 14. TREEMAP
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [14/23] treemap...")
    df_tree = df.groupby(["region", "product"])["revenue"].sum().reset_index()
    fig_tree = charts.make_figure(
        df_tree, chart="treemap", x="product", y="revenue", color="region",
        currency="INR"
    )
    paths = export_figure(fig_tree, "14_treemap", is_wide=True)
    gallery_index.append({"id": "treemap", "paths": paths, "meta": fig_tree.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 15. FUNNEL
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [15/23] funnel...")
    df_funnel = pd.DataFrame([
        {"stage": "Leads Captured", "count": 1420},
        {"stage": "Qualified Demo", "count": 890},
        {"stage": "Proposal Sent", "count": 480},
        {"stage": "Contract Review", "count": 270},
        {"stage": "Deals Won", "count": 165},
    ])
    fig_funnel = charts.make_figure(df_funnel, chart="funnel", x="stage", y="count")
    paths = export_figure(fig_funnel, "15_funnel")
    gallery_index.append({"id": "funnel", "paths": paths, "meta": fig_funnel.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 16. SCATTER
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [16/23] scatter...")
    df_scatter = df[["units", "revenue"]].dropna()
    fig_scatter = charts.make_figure(
        df_scatter, chart="scatter", x="units", y="revenue",
        currency="INR"
    )
    paths = export_figure(fig_scatter, "16_scatter")
    gallery_index.append({"id": "scatter", "paths": paths, "meta": fig_scatter.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 17. BUBBLE
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [17/23] bubble...")
    df_bubble = df.groupby("product").agg({
        "units": "sum",
        "revenue": "sum",
        "satisfaction_rating": "mean"
    }).reset_index()
    df_bubble.columns = ["product", "units", "revenue", "size"]
    fig_bubble = charts.make_figure(
        df_bubble, chart="bubble", x="units", y="revenue", color="product",
        currency="INR"
    )
    paths = export_figure(fig_bubble, "17_bubble")
    gallery_index.append({"id": "bubble", "paths": paths, "meta": fig_bubble.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 18. HEATMAP
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [18/23] heatmap...")
    df_heat = df.pivot_table(
        index="region", columns="product", values="revenue", aggfunc="sum", fill_value=0
    ).reset_index()
    fig_heat = charts.make_figure(df_heat, chart="heatmap", currency="INR")
    paths = export_figure(fig_heat, "18_heatmap", is_wide=True)
    gallery_index.append({"id": "heatmap", "paths": paths, "meta": fig_heat.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 19. HISTOGRAM (Freedman-Diaconis + median line)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [19/23] histogram...")
    fig_hist = charts.make_figure(
        df[["revenue"]], chart="histogram", x="revenue",
        currency="INR"
    )
    paths = export_figure(fig_hist, "19_histogram")
    gallery_index.append({"id": "histogram", "paths": paths, "meta": fig_hist.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 20. BOX PLOT (Outliers only, sorted medians)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [20/23] box...")
    fig_box = charts.make_figure(
        df[["region", "revenue"]], chart="box", x="region", y="revenue",
        currency="INR"
    )
    paths = export_figure(fig_box, "20_box")
    gallery_index.append({"id": "box", "paths": paths, "meta": fig_box.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 21. TABLE
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [21/23] table...")
    df_tab = df[["region", "product", "units", "revenue"]].head(12)
    fig_tab = charts.make_figure(df_tab, chart="table", currency="INR")
    paths = export_figure(fig_tab, "21_table", is_wide=True)
    gallery_index.append({"id": "table", "paths": paths, "meta": fig_tab.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 22. PIVOT
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [22/23] pivot...")
    df_piv = df.pivot_table(
        index="region", columns="product", values="units", aggfunc="sum", fill_value=0
    ).reset_index()
    fig_piv = charts.make_figure(df_piv, chart="pivot")
    paths = export_figure(fig_piv, "22_pivot", is_wide=True)
    gallery_index.append({"id": "pivot", "paths": paths, "meta": fig_piv.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # 23. LIKERT STACK
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating [23/23] likert_stack...")
    df_likert = df.groupby(["region", "satisfaction_rating"]).size().reset_index(name="responses")
    df_likert["rating_label"] = df_likert["satisfaction_rating"].astype(str) + " Star"
    fig_likert = charts.make_figure(
        df_likert, chart="likert_stack", x="region", y="responses", color="rating_label"
    )
    paths = export_figure(fig_likert, "23_likert_stack", is_wide=True)
    gallery_index.append({"id": "likert_stack", "paths": paths, "meta": fig_likert.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # STRESS CASE 1: 200 CATEGORIES (Tests Top-N + "Other" Collapse & Auto-Horizontal)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating Stress Case 1: 200 Categories (Top 10 + Other)...")
    np.random.seed(42)
    cat_names = [f"Product SKU {i:03d} Description Extended" for i in range(1, 201)]
    cat_vals = np.random.exponential(scale=50000, size=200) + 1000
    df_stress_cats = pd.DataFrame({"sku": cat_names, "sales": cat_vals})
    fig_stress_cats = charts.make_figure(
        df_stress_cats, chart="bar", x="sku", y="sales", currency="INR"
    )
    paths = export_figure(fig_stress_cats, "stress_200_categories", is_wide=True)
    gallery_index.append({"id": "stress_200_categories", "paths": paths, "meta": fig_stress_cats.get("datapilot_meta", {})})

    # ─────────────────────────────────────────────────────────────────────────
    # STRESS CASE 2: 5,000 TIME POINTS (Tests Auto-Grain Aggregation & WebGL)
    # ─────────────────────────────────────────────────────────────────────────
    print("Generating Stress Case 2: 5,000 Time Points (Auto-Aggregation)...")
    date_rng = pd.date_range("2020-01-01", periods=5000, freq="h")
    # Sine wave + trend + noise
    t_vals = np.linspace(0, 50, 5000)
    noise = np.random.normal(0, 5, 5000)
    time_series_vals = 1000 + 10 * t_vals + 50 * np.sin(t_vals) + noise
    df_stress_time = pd.DataFrame({"timestamp": date_rng, "load": time_series_vals})
    fig_stress_time = charts.make_figure(
        df_stress_time, chart="line", x="timestamp", y="load"
    )
    paths = export_figure(fig_stress_time, "stress_5000_timepoints", is_wide=True)
    gallery_index.append({"id": "stress_5000_timepoints", "paths": paths, "meta": fig_stress_time.get("datapilot_meta", {})})

    # Write summary index
    index_file = GALLERY_DIR / "gallery_index.json"
    index_file.write_text(json.dumps(gallery_index, indent=2))
    print(f"\nSuccessfully generated {len(gallery_index)} visual sets (each at 3 sizes) in {GALLERY_DIR}!")


if __name__ == "__main__":
    main()
