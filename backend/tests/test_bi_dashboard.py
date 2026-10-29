"""
Unit tests for Power BI / Tableau Inspired Dashboard Engine (PART B).
"""
import pytest
import pandas as pd
import numpy as np
from app.services.dashboard_engine import (
    humanize_name,
    get_measure_label,
    get_stable_colors,
    clean_and_prepare_df_types,
    detect_available_filters,
    apply_filters_to_df,
    compute_kpis,
    build_suitable_charts,
    compute_consolidated_insights,
    get_dashboard_payload,
)


def test_humanize_name():
    assert humanize_name("order_date") == "Order Date"
    assert humanize_name("unit_price") == "Unit Price"
    assert humanize_name("qty") == "Quantity"
    assert humanize_name("cust_id") == "Customer ID"
    assert humanize_name("gst_number") == "GST Number"
    assert humanize_name("pan_card") == "PAN Card"
    assert humanize_name("sku_code") == "SKU Code"


def test_measure_labels():
    assert get_measure_label("revenue", "sum") == "Total Revenue"
    assert get_measure_label("qty", "sum") == "Total Quantity"
    assert get_measure_label("unit_price", "mean") == "Average Unit Price"
    assert get_measure_label("order_id", "distinct") == "Distinct Order ID"


def test_stable_colors():
    cats = ["North", "South", "East", "West", "Central", "Overseas", "Extra1", "Extra2"]
    colors = get_stable_colors(cats)
    assert len(colors) == len(cats)
    # First 6 should be palette colors, 7th onwards should be neutral slate grey (#94A3B8)
    assert colors[0] == "#0B7A75"
    assert colors[5] == "#DC2626"
    assert colors[6] == "#94A3B8"
    assert colors[7] == "#94A3B8"


def test_bi_dashboard_payload():
    df = pd.DataFrame({
        "order_id": [f"ORD-{i:03d}" for i in range(1, 21)],
        "order_date": pd.date_range("2025-01-01", periods=20, freq="D"),
        "region": ["North", "South", "East", "West"] * 5,
        "category": ["Electronics", "Furniture"] * 10,
        "revenue": [1000 + i * 150 for i in range(20)],
        "qty": [1 + (i % 4) for i in range(20)],
        "satisfaction_rating": [4, 5, 3, 4, 5] * 4,
    })

    payload = get_dashboard_payload(df, "Test BI Dataset", "ds_test_1")

    # Assert basic payload structures
    assert payload["total_rows"] == 20
    assert payload["filtered_rows"] == 20
    assert payload["last_updated_at"] is not None
    assert len(payload["kpis"]) >= 3
    assert len(payload["charts"]) >= 4
    assert len(payload["insights"]) >= 5

    # Check Slicer Detection
    avail = payload["available_filters"]
    assert avail["date_filter"] is not None
    assert avail["date_filter"]["min"] == "2025-01-01"
    assert len(avail["category_filters"]) >= 1
    # Check item counts exist in options
    cat_opts = avail["category_filters"][0]["options"]
    assert len(cat_opts) > 0
    assert "count" in cat_opts[0]
    assert cat_opts[0]["count"] > 0

    # Check that charts have table_data attached
    chart_with_table = next((c for c in payload["charts"] if "table_data" in c), None)
    assert chart_with_table is not None
    td = chart_with_table["table_data"]
    assert "columns" in td
    assert "rows" in td
    assert "total" in td
    assert len(td["rows"]) > 0
    assert "percent_of_max" in td["rows"][0]


def test_cross_filter_execution():
    df = pd.DataFrame({
        "region": ["North", "North", "South", "East"],
        "revenue": [100, 200, 300, 400],
    })
    # Apply cross-filter on region == North
    filtered = apply_filters_to_df(df, {"cross_dim": "region", "cross_val": "North"})
    assert len(filtered) == 2
    assert (filtered["region"] == "North").all()
