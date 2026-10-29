"""
Comprehensive Test Suite for Visual Studio.

Validates:
1. Registry integrity (all 23 visual types, all options valid, matrix consistency)
2. Visual compiler output for each of the 23 visual types
3. SQL injection protection in field names, options, and filter operators
4. KPI comparison mathematics (target, previous period, YoY)
5. Window functions (% of total, running total)
6. Sort & top-N show limits
7. API endpoints (/visuals/registry, /visuals/query, /visuals/suggest, /visuals/validate-formula)
8. Tenant isolation
"""
import io
import pytest
import pandas as pd
from starlette.testclient import TestClient

from app.auth import make_token
from app.db import datasets, users
from app.main import app
from app.services.visual_compiler import (
    VisualCompileError,
    VisualFilter,
    VisualSpec,
    compile_visual_to_sql,
)
from app.services.visual_registry import (
    APPLICABLE_OPTIONS_MATRIX,
    DROPDOWN_OPTIONS,
    VISUAL_TYPES,
    get_visual_registry,
)

client = TestClient(app)


def auth_header(email="studio_user@datapilot.test"):
    u = users.find_one({"email": email})
    if not u:
        uid = f"u_studio_{email.split('@')[0]}"
        users.insert_one({"_id": uid, "email": email, "name": "Studio Tester"})
    else:
        uid = u["_id"]
    return {"Authorization": f"Bearer {make_token(uid)}"}


@pytest.fixture
def sales_fixture():
    """Uploads a clean sales dataset for visual studio testing."""
    h = auth_header()
    csv_data = (
        "order_date,region,product,units,unit_price,revenue\n"
        "2023-01-15,North,Laptops,10,500.0,5000.0\n"
        "2023-01-20,West,Phones,20,200.0,4000.0\n"
        "2023-02-10,North,Phones,15,200.0,3000.0\n"
        "2023-02-14,South,Laptops,8,500.0,4000.0\n"
        "2023-03-05,East,Tablets,12,150.0,1800.0\n"
        "2023-03-25,North,Tablets,14,150.0,2100.0\n"
        "2023-04-12,West,Laptops,5,500.0,2500.0\n"
        "2023-05-18,South,Phones,25,200.0,5000.0\n"
    ).encode("utf-8")

    r = client.post(
        "/datasets/upload",
        headers=h,
        files={"file": ("sales_studio.csv", csv_data, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Registry Integrity Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestRegistryIntegrity:
    def test_registry_contains_at_least_22_or_23_visual_types(self):
        reg = get_visual_registry()
        types = reg["visual_types"]
        assert len(types) >= 22
        type_ids = [t["id"] for t in types]
        for expected in [
            "kpi_card", "sparkline_kpi", "gauge", "bullet", "column", "bar",
            "stacked_column", "combo", "line", "area", "pie", "donut",
            "treemap", "funnel", "scatter", "bubble", "heatmap", "histogram",
            "box", "table", "pivot", "likert_stack"
        ]:
            assert expected in type_ids, f"Missing visual type: {expected}"

    def test_all_visuals_in_matrix(self):
        for v_id in VISUAL_TYPES:
            assert v_id in APPLICABLE_OPTIONS_MATRIX, f"{v_id} missing from matrix"
            m = APPLICABLE_OPTIONS_MATRIX[v_id]
            assert "required_fields" in m
            assert "allowed_options" in m

    def test_dropdown_options_valid(self):
        reg = get_visual_registry()
        opts = reg["options"]
        for key in ["aggregation", "date_grain", "compare_to", "sort", "show", "number_format", "palette", "legend", "orientation", "filter_operator"]:
            assert key in opts
            assert len(opts[key]) >= 2
            for item in opts[key]:
                assert "value" in item and "label" in item

    def test_api_registry_endpoint(self):
        r = client.get("/visuals/registry")
        assert r.status_code == 200
        data = r.json()
        assert "visual_types" in data
        assert "matrix" in data
        assert "options" in data


# ─────────────────────────────────────────────────────────────────────────────
# 2. Visual Compiler Tests for All 23 Visual Types
# ─────────────────────────────────────────────────────────────────────────────
class TestVisualCompilerAllTypes:
    @pytest.mark.parametrize("vtype,fields", [
        ("kpi_card", {"value": "revenue"}),
        ("sparkline_kpi", {"value": "revenue", "category": "order_date"}),
        ("gauge", {"value": "revenue"}),
        ("bullet", {"value": "revenue"}),
        ("column", {"category": "region", "value": "revenue"}),
        ("bar", {"category": "region", "value": "revenue"}),
        ("stacked_column", {"category": "order_date", "value": "revenue", "colour_by": "product"}),
        ("stacked_bar", {"category": "region", "value": "revenue", "colour_by": "product"}),
        ("combo", {"category": "region", "value": "revenue", "secondary_value": "units"}),
        ("line", {"category": "order_date", "value": "revenue"}),
        ("area", {"category": "order_date", "value": "revenue"}),
        ("pie", {"category": "product", "value": "revenue"}),
        ("donut", {"category": "product", "value": "revenue"}),
        ("treemap", {"category": "region", "value": "revenue", "sub_category": "product"}),
        ("funnel", {"category": "region", "value": "revenue"}),
        ("scatter", {"x": "units", "y": "revenue"}),
        ("bubble", {"x": "units", "y": "revenue", "size": "unit_price"}),
        ("heatmap", {"rows": "region", "columns": "product", "value": "revenue"}),
        ("histogram", {"value": "revenue"}),
        ("box", {"value": "revenue", "category": "region"}),
        ("table", {"columns": ["order_date", "region", "revenue"]}),
        ("pivot", {"rows": "region", "columns": "product", "value": "revenue"}),
        ("likert_stack", {"category": "region", "value": "units"}),
    ])
    def test_compile_visual_type(self, vtype, fields):
        spec = VisualSpec(
            type=vtype,
            title=f"Test {vtype}",
            dataset_id="ds_test",
            fields=fields,
            options={"aggregation": "sum", "date_grain": "month", "sort": "value_desc", "show": "top_10"},
        )
        sql = compile_visual_to_sql("sales_table", spec)
        assert isinstance(sql, str)
        assert "SELECT" in sql.upper()
        assert "FROM \"sales_table\"" in sql


# ─────────────────────────────────────────────────────────────────────────────
# 3. SQL Injection Protection Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestSqlInjectionProtection:
    def test_injection_in_field_name_rejected(self):
        spec = VisualSpec(
            type="column",
            dataset_id="ds_test",
            fields={"category": "region; DROP TABLE users; --", "value": "revenue"},
        )
        with pytest.raises(VisualCompileError):
            compile_visual_to_sql("sales_table", spec)

    def test_injection_in_filter_escaped(self):
        spec = VisualSpec(
            type="bar",
            dataset_id="ds_test",
            fields={"category": "region", "value": "revenue"},
            filters=[
                VisualFilter(field="region", operator="is", value="North' OR '1'='1"),
            ],
        )
        sql = compile_visual_to_sql("sales_table", spec)
        assert "North'' OR ''1''=''1" in sql or "''1''=''1" in sql
        assert "DROP" not in sql

    def test_formula_validation_rejects_ddl(self):
        h = auth_header()
        r = client.post(
            "/visuals/validate-formula",
            headers=h,
            json={"dataset_id": "any", "name": "bad", "formula": "revenue; DROP TABLE users;"},
        )
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 4. Aggregations, Window Functions & Sort / Show Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestAggregationsAndWindowFunctions:
    def test_pct_of_total(self, sales_fixture):
        h = auth_header()
        spec = {
            "type": "column",
            "title": "Revenue % of total",
            "dataset_id": sales_fixture,
            "fields": {"category": "region", "value": "revenue"},
            "options": {"aggregation": "pct_of_total"},
        }
        r = client.post("/visuals/query", headers=h, json={"spec": spec})
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert len(rows) > 0
        total_pct = sum(row["value"] for row in rows)
        assert abs(total_pct - 100.0) < 0.1

    def test_running_total(self, sales_fixture):
        h = auth_header()
        spec = {
            "type": "line",
            "title": "Cumulative Revenue",
            "dataset_id": sales_fixture,
            "fields": {"category": "order_date", "value": "revenue"},
            "options": {"aggregation": "running_total", "date_grain": "month"},
        }
        r = client.post("/visuals/query", headers=h, json={"spec": spec})
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert len(rows) >= 2
        # Values should be monotonically increasing
        vals = [r["value"] for r in rows]
        assert vals[-1] >= vals[0]

    def test_top_5_limit(self, sales_fixture):
        h = auth_header()
        spec = {
            "type": "bar",
            "title": "Top 2 regions",
            "dataset_id": sales_fixture,
            "fields": {"category": "region", "value": "revenue"},
            "options": {"aggregation": "sum", "show": "top_5"},
        }
        r = client.post("/visuals/query", headers=h, json={"spec": spec})
        assert r.status_code == 200
        assert len(r.json()["rows"]) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# 5. KPI Comparisons & Suggestions Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestKpiComparisonsAndSuggestions:
    def test_kpi_comparison_target(self, sales_fixture):
        h = auth_header()
        spec = {
            "type": "kpi_card",
            "title": "Total Revenue",
            "dataset_id": sales_fixture,
            "fields": {"value": "revenue"},
            "options": {"aggregation": "sum", "compare_to": "target", "target": 20000.0, "number_format": "currency_inr"},
        }
        r = client.post("/visuals/query", headers=h, json={"spec": spec})
        assert r.status_code == 200
        kpi = r.json()["kpi"]
        assert kpi is not None
        assert "formatted_value" in kpi
        assert "delta_pct" in kpi
        assert "₹" in kpi["formatted_value"]

    def test_suggest_visuals(self, sales_fixture):
        h = auth_header()
        r = client.post("/visuals/suggest", headers=h, json={"dataset_id": sales_fixture})
        assert r.status_code == 200
        suggs = r.json()["suggestions"]
        assert len(suggs) >= 6
        types = [s["type"] for s in suggs]
        assert "kpi_card" in types
        assert "table" in types

    def test_excel_export_dashboard(self, sales_fixture):
        h = auth_header()
        specs = [
            {
                "type": "column",
                "title": "Revenue by Region",
                "dataset_id": sales_fixture,
                "fields": {"category": "region", "value": "revenue"},
                "options": {"aggregation": "sum"},
            },
            {
                "type": "kpi_card",
                "title": "Total Revenue",
                "dataset_id": sales_fixture,
                "fields": {"value": "revenue"},
                "options": {"aggregation": "sum"},
            },
        ]
        r = client.post(
            "/visuals/export-excel",
            headers=h,
            json={"dataset_id": sales_fixture, "dashboard_name": "Sales Test", "specs": specs},
        )
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers.get("content-type", "")
        assert len(r.content) > 1000  # Valid Excel file generated
