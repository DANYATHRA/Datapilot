"""Tests for new data engineering & BI analyst services:
- Connectors & URL security
- Quality scorecard & custom rules
- Modelling & relationship detection
- Pipeline engine & code export
- Domain KPI catalogue & computation
- Requirements / Projects workspace
- Documentation & presentation generation
"""

import pandas as pd
import pytest

from app.services import connectors as conn_svc
from app.services import documentation as doc_svc
from app.services import kpi_catalogue as kpi_svc
from app.services import modelling as model_svc
from app.services import pipeline_engine as pe_svc
from app.services import projects as proj_svc
from app.services import quality as quality_svc


# ── Connectors & Security Tests ────────────────────────────────────────

def test_url_security_blocks_private_ips():
    with pytest.raises(ValueError, match="Blocked"):
        conn_svc._validate_url_safe("http://127.0.0.1/data.csv")
    with pytest.raises(ValueError, match="Blocked"):
        conn_svc._validate_url_safe("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError, match="Blocked"):
        conn_svc._validate_url_safe("http://localhost:8000/data.csv")


def test_sqlite_connector_query(tmp_path):
    import sqlite3
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, product TEXT, revenue REAL)")
    conn.execute("INSERT INTO sales VALUES (1, 'Widget A', 150.0)")
    conn.execute("INSERT INTO sales VALUES (2, 'Widget B', 250.0)")
    conn.commit()
    conn.close()

    doc = {"type": "sqlite", "file_path": str(db_file), "host": "", "database": ""}
    engine = conn_svc._make_engine(doc)
    df = pd.read_sql("SELECT * FROM sales", engine)
    assert len(df) == 2
    assert "revenue" in df.columns


# ── Quality Scorecard & Custom Rules Tests ──────────────────────────────

def test_quality_scorecard_calculation():
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "email": ["a@b.com", "c@d.com", None, "e@f.com", "g@h.com"],
        "age": [25, 30, 45, 12, 60],
        "status": ["active", "active", "pending", "active", "invalid_status"],
    })
    scorecard = quality_svc.compute_quality_scorecard(df)
    assert "overall_score" in scorecard
    assert "dimensions" in scorecard
    assert scorecard["dimensions"]["completeness"]["score"] < 100  # because email has null
    assert scorecard["dimensions"]["uniqueness"]["score"] == 100


def test_custom_rule_evaluation():
    df = pd.DataFrame({
        "age": [25, 30, -5, 150, 40],
        "status": ["active", "pending", "active", "archived", "unknown"],
    })
    rule_range = {
        "_id": "r1", "name": "Valid Age", "column": "age",
        "rule_type": "range", "params": {"min": 0, "max": 120}, "severity": "error",
    }
    res_range = quality_svc.evaluate_rule(df, rule_range)
    assert res_range["fail_count"] == 2  # -5 and 150

    rule_allowed = {
        "_id": "r2", "name": "Allowed Status", "column": "status",
        "rule_type": "allowed_values", "params": {"values": ["active", "pending", "archived"]}, "severity": "warning",
    }
    res_allowed = quality_svc.evaluate_rule(df, rule_allowed)
    assert res_allowed["fail_count"] == 1  # "unknown"


# ── Modelling & Relationships Tests ────────────────────────────────────

def test_candidate_key_detection():
    df = pd.DataFrame({
        "customer_id": [f"CUST_{i}" for i in range(100)],
        "country": ["USA"] * 50 + ["UK"] * 50,
        "score": list(range(100)),
    })
    keys = model_svc.detect_candidate_keys(df)
    key_cols = [k["column"] for k in keys]
    assert "customer_id" in key_cols
    assert "country" not in key_cols


def test_relationship_detection_and_validation():
    customers = pd.DataFrame({
        "customer_id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
    })
    orders = pd.DataFrame({
        "order_id": [101, 102, 103, 104, 105, 106],
        "customer_id": [1, 2, 2, 3, 4, 999],  # 999 is orphan FK
        "amount": [50, 60, 70, 80, 90, 100],
    })
    tables = {"customers": customers, "orders": orders}
    candidates = model_svc.detect_relationships(tables)
    assert len(candidates) >= 1
    top = candidates[0]
    assert "customer_id" in (top["from_column"], top["to_column"])

    # Validate relationship with orphan check (PK table: customers, FK table: orders)
    validation = model_svc.validate_relationship(customers, "customer_id", orders, "customer_id")
    assert validation["orphan_count"] == 1
    assert 999 in validation["orphan_samples"]


def test_date_dimension_generator():
    dim = model_svc.generate_date_dimension("2024-01-01", "2024-01-31")
    assert len(dim) == 31
    assert "year" in dim.columns
    assert "month_name" in dim.columns
    assert "is_weekend" in dim.columns


# ── Pipeline Engine & Code Export Tests ─────────────────────────────────

def test_pipeline_engine_transforms_and_code_gen():
    df = pd.DataFrame({
        "category": ["A", "B", "A", "B", "A"],
        "sales": [100, 200, 150, 300, 250],
        "quantity": [2, 4, 3, 5, 4],
    })
    # Filter
    data = {"source": df}
    step_filter = {"name": "f1", "type": "filter", "category": "transform", "input": "source", "output": "filtered", "params": {"expression": "sales > 120"}}
    pe_svc._execute_transform(step_filter, data)
    assert len(data["filtered"]) == 4

    # Calculated column
    step_calc = {"name": "c1", "type": "calculated_column", "category": "transform", "input": "filtered", "output": "with_price", "params": {"name": "unit_price", "expression": "sales / quantity"}}
    pe_svc._execute_transform(step_calc, data)
    assert "unit_price" in data["with_price"].columns

    # Code generation tests
    pipeline_def = {
        "steps": [
            {"type": "dataset", "name": "load_sales", "dataset_id": "ds1", "output": "sales_df"},
            {"type": "filter", "name": "high_sales", "input": "sales_df", "output": "high_df", "params": {"expression": "sales > 100"}},
            {"type": "aggregate", "name": "grp", "input": "high_df", "output": "summary_df", "params": {"group_by": ["category"], "aggregations": {"sales": "sum"}}},
        ]
    }
    py_code = pe_svc.export_as_python(pipeline_def)
    assert "pandas" in py_code
    assert "groupby" in py_code

    sql_code = pe_svc.export_as_sql(pipeline_def)
    assert "SELECT" in sql_code
    assert "GROUP BY" in sql_code

    r_code = pe_svc.export_as_r(pipeline_def)
    assert "tidyverse" in r_code
    assert "filter" in r_code


# ── Domain KPI Catalogue Tests ─────────────────────────────────────────

def test_kpi_detection_and_computation():
    sales_df = pd.DataFrame({
        "order_id": [101, 102, 103, 104, 105],
        "revenue": [100.0, 250.0, 300.0, 150.0, 200.0],
        "quantity": [1, 2, 3, 1, 2],
        "discount": [0.05, 0.10, 0.0, 0.15, 0.0],
        "region": ["North", "South", "East", "West", "North"],
    })
    domain, roles = kpi_svc.detect_domain_and_roles(sales_df)
    assert domain == "Sales"
    assert "revenue" in roles

    kpis = kpi_svc.get_available_kpis(domain, roles)
    rev_kpi = next((k for k in kpis if k["name"] == "Total Revenue"), None)
    assert rev_kpi is not None
    assert rev_kpi["available"] is True

    computed = kpi_svc.compute_kpi(sales_df, rev_kpi, roles)
    assert computed["value"] == 1000.0
    assert "1.0K" in computed["formatted"]


# ── Projects / Requirements Workspace Tests ────────────────────────────

def test_generate_analysis_plan():
    columns = [
        {"name": "order_date", "kind": "datetime"},
        {"name": "region", "kind": "text"},
        {"name": "sales", "kind": "numeric"},
        {"name": "profit", "kind": "numeric"},
    ]
    plan = proj_svc.generate_analysis_plan(
        "Why did sales drop in Q3?",
        columns,
    )
    assert "suggested_methodologies" in plan
    methods = [m["method"] for m in plan["suggested_methodologies"]]
    assert "trend_analysis" in methods
    assert len(plan["suggested_metrics"]) >= 2


def test_project_crud_and_persistence():
    owner = "test_user_persistence"
    # Create project
    proj = proj_svc.create_project(owner, {
        "name": "Q3 Sales Deep Dive",
        "business_question": "Why did conversion drop in Q3?",
        "deliverables": [{"id": "d1", "title": "Profile data", "done": False}],
    })
    p_id = proj["_id"]
    assert proj["name"] == "Q3 Sales Deep Dive"
    assert proj["status"] == "draft"

    # Partial update without name
    updated = proj_svc.update_project(owner, p_id, {
        "status": "complete",
        "deliverables": [{"id": "d1", "title": "Profile data", "done": True}],
    })
    assert updated["status"] == "complete"
    assert updated["deliverables"][0]["done"] is True
    assert updated["name"] == "Q3 Sales Deep Dive"

    # List projects includes it
    all_projs = proj_svc.list_projects(owner)
    assert any(p["_id"] == p_id for p in all_projs)

    # Delete project
    proj_svc.delete_project(owner, p_id)
    with pytest.raises(ValueError, match="not found"):
        proj_svc.get_project(owner, p_id)



# ── Documentation & Presentation Tests ─────────────────────────────────

def test_data_dictionary_and_deck_generation():
    df = pd.DataFrame({
        "customer_id": [1, 2, 3],
        "email": ["alice@corp.com", "bob@corp.com", "charlie@corp.com"],
        "category": ["A", "B", "A"],
        "spend": [100.0, 200.0, 300.0],
    })
    profile_data = {
        "columns": [
            {"name": "customer_id", "kind": "numeric", "dtype": "int64", "null_pct": 0, "nulls": 0, "unique": 3},
            {"name": "email", "kind": "text", "dtype": "object", "null_pct": 0, "nulls": 0, "unique": 3, "semantic_type": "email"},
            {"name": "category", "kind": "text", "dtype": "object", "null_pct": 0, "nulls": 0, "unique": 2},
            {"name": "spend", "kind": "numeric", "dtype": "float64", "null_pct": 0, "nulls": 0, "unique": 3},
        ],
        "pii_columns": {"email": "email"},
        "rows": 3,
        "cols": 4,
        "quality": {"score": 98, "completeness": 100, "uniqueness": 100},
    }
    # Test data dictionary (PII redacted)
    dd = doc_svc.generate_data_dictionary(df, profile_data, "Customers")
    email_entry = next(e for e in dd if e["column"] == "email")
    assert email_entry["is_pii"] is True
    assert "[REDACTED]" in email_entry["example_values"][0]

    # Test PowerPoint generation
    pptx_bytes = doc_svc.generate_powerpoint_deck(
        dataset_name="Customer Analysis",
        profile=profile_data,
        insights=[{"text": "Top segment accounts for 60% of revenue", "evidence": "spend sum = 600"}],
        kpi_values=[{"name": "Total Spend", "formatted": "$600", "definition": "Sum of spend"}],
    )
    assert len(pptx_bytes) > 1000
    assert pptx_bytes[:4] == b"PK\x03\x04"  # Valid ZIP / PPTX magic bytes
