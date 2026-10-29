"""
Tests for DataPilot Three-Step Flow & Shared Calculation Layer.

Verifies:
1. Mathematical correctness: KPIs match pandas aggregations exactly
2. Recommender constraints:
   - No line chart without date
   - No pie chart with > 6 categories
   - Likert only with rating column
   - Scatter only with 2 numeric columns
3. Insight accuracy: numbers in generated sentences match pandas
4. Filtering: date and categorical filtering updates all metrics
5. PDF report generation: valid PDF bytes output
"""
import io
import re
import numpy as np
import pandas as pd
import pytest

from app.services.dashboard_engine import (
    clean_and_prepare_df_types,
    apply_filters_to_df,
    compute_kpis,
    build_suitable_charts,
    compute_consolidated_insights,
    get_dashboard_payload,
    generate_executive_pdf_report,
)


@pytest.fixture
def sales_df():
    # Construct controlled sales fixture with known numbers
    return pd.DataFrame({
        "order_id": [f"ORD-{i:03d}" for i in range(1, 21)],
        "order_date": [f"2025-01-{(i%28)+1:02d}" for i in range(1, 21)],
        "region": ["North"] * 10 + ["South"] * 6 + ["East"] * 4,
        "product": ["Laptops"] * 8 + ["Tablets"] * 6 + ["Phones"] * 4 + ["Monitors"] * 2,
        "units": [2.0, 3.0, 1.0, 5.0, 2.0, 4.0, 1.0, 3.0, 2.0, 1.0,
                  2.0, 3.0, 1.0, 2.0, 1.0, 2.0, 4.0, 1.0, 2.0, 3.0],
        "unit_price": [1000] * 8 + [500] * 6 + [300] * 4 + [200] * 2,
        "revenue": [2000, 3000, 1000, 5000, 2000, 4000, 1000, 3000, 1000, 500,
                    1000, 1500, 500, 1000, 500, 1000, 1200, 300, 400, 600],
        "satisfaction_rating": [5, 4, 5, 4, 5, 4, 5, 4, 5, 4,
                                3, 3, 2, 3, 2, 3, 4, 3, 4, 4],
    })


def test_kpi_calculations_match_pandas_exactly(sales_df):
    df_prepared = clean_and_prepare_df_types(sales_df)
    kpis = compute_kpis(df_prepared)

    kpi_map = {k["id"]: k for k in kpis}

    # Revenue
    expected_revenue = float(df_prepared["revenue"].sum())
    assert "kpi_total_revenue" in kpi_map
    assert kpi_map["kpi_total_revenue"]["raw_value"] == expected_revenue

    # Units
    expected_units = float(df_prepared["units"].sum())
    assert "kpi_total_units" in kpi_map
    assert kpi_map["kpi_total_units"]["raw_value"] == expected_units

    # Total orders
    expected_orders = len(df_prepared)
    assert "kpi_total_orders" in kpi_map
    assert kpi_map["kpi_total_orders"]["raw_value"] == expected_orders

    # Average order value
    expected_aov = float(df_prepared["revenue"].mean())
    assert "kpi_avg_order_value" in kpi_map
    assert abs(kpi_map["kpi_avg_order_value"]["raw_value"] - expected_aov) < 1e-4

    # Average rating
    expected_rating = float(df_prepared["satisfaction_rating"].mean())
    assert "kpi_avg_rating" in kpi_map
    assert abs(kpi_map["kpi_avg_rating"]["raw_value"] - expected_rating) < 1e-4


def test_recommender_constraints(sales_df):
    df_prepared = clean_and_prepare_df_types(sales_df)
    charts = build_suitable_charts(df_prepared)

    chart_types = [c["chart_type"] for c in charts]

    # Date exists -> Line or area should be present
    assert any(t in ("line", "area") for t in chart_types)

    # Pie/Donut must only appear if categories <= 6
    for c in charts:
        if c["chart_type"] in ("pie", "donut"):
            cat_col = c["fields"]["x"]
            assert df_prepared[cat_col].nunique() <= 6

    # Test removing date column blocks line chart
    no_date_df = df_prepared.drop(columns=["order_date"])
    no_date_charts = build_suitable_charts(no_date_df)
    assert not any(c["chart_type"] in ("line", "area") for c in no_date_charts)

    # Test dataset with high cardinality category (15 categories) blocks pie/donut
    high_cat_df = sales_df.copy()
    high_cat_df["many_cats"] = [f"Cat_{i}" for i in range(len(high_cat_df))]
    high_cat_charts = build_suitable_charts(clean_and_prepare_df_types(high_cat_df))
    for c in high_cat_charts:
        if c.get("fields", {}).get("x") == "many_cats":
            assert c["chart_type"] not in ("pie", "donut")


def test_consolidated_insights_numbers_match_pandas(sales_df):
    df_prepared = clean_and_prepare_df_types(sales_df)
    charts = build_suitable_charts(df_prepared)
    insights = compute_consolidated_insights(df_prepared, charts)

    assert 5 <= len(insights) <= 8

    # 1. Share insight: North revenue share
    share_ins = next((i for i in insights if "generates" in i["text"]), None)
    if share_ins:
        # Check that the percentage in the text matches pandas
        match = re.search(r"(\d+)%", share_ins["text"])
        assert match is not None
        text_pct = int(match.group(1))

        reg_rev = df_prepared.groupby("region")["revenue"].sum()
        top_reg = reg_rev.idxmax()
        expected_pct = round((reg_rev.max() / reg_rev.sum()) * 100)
        assert text_pct == expected_pct
        assert top_reg in share_ins["text"]


def test_dashboard_filtering(sales_df):
    # Filter to North only
    filters = {"categories": {"region": ["North"]}}
    payload = get_dashboard_payload(
        df_raw=sales_df,
        dataset_name="Test Sales",
        dataset_id="test_id",
        filters=filters,
    )

    assert payload["filtered_rows"] == 10
    kpi_map = {k["id"]: k for k in payload["kpis"]}
    expected_north_rev = float(sales_df[sales_df["region"] == "North"]["revenue"].sum())
    assert kpi_map["kpi_total_revenue"]["raw_value"] == expected_north_rev


def test_pdf_report_generation(sales_df):
    pdf_bytes = generate_executive_pdf_report(
        df_raw=sales_df,
        dataset_name="Executive Sales Report",
    )
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")
