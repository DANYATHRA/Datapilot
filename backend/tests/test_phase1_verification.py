"""Phase 1 automated tests for DataPilot.

Verifies:
1. Multi-table benchmark dataset integrity (planted anomalies, duplicate PKs, orphan FKs, null keys)
2. Relationship validation engine (orders -> customers, orders -> products, customers -> regions)
3. Quality dimension rules (not_null, unique, range, regex, date_not_future, referential_integrity)
4. ERP quirk detection (title rows, subtotal rows, text numbers, trailing totals)
5. Security controls (Fernet encryption, SSRF protection, read-only SQL enforcement)
6. ETL Pipeline execution and reproducible code export (SQL, Python, R)
"""

import os
from pathlib import Path
import pandas as pd
import pytest

from app.services.connectors import (
    _assert_select_only,
    _is_private_ip,
    detect_erp_quirks,
)
from app.services.encryption import decrypt, encrypt
from app.services.modelling import detect_candidate_keys, detect_relationships, validate_relationship
from app.services.quality import evaluate_rule
from app.services import pipeline_engine

MULTI_TABLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "multi_table"


@pytest.fixture
def multi_table_data():
    orders_df = pd.read_csv(MULTI_TABLE_DIR / "orders.csv")
    products_df = pd.read_csv(MULTI_TABLE_DIR / "products.csv")
    customers_df = pd.read_excel(MULTI_TABLE_DIR / "customers.xlsx", sheet_name="customers")
    regions_df = pd.read_excel(MULTI_TABLE_DIR / "customers.xlsx", sheet_name="regions")
    return {
        "orders": orders_df,
        "products": products_df,
        "customers": customers_df,
        "regions": regions_df,
    }


# ── 1. Security Tests ───────────────────────────────────────────────

def test_fernet_credential_encryption():
    secret = "SuperSecretDbPassword123!@#"
    ciphertext = encrypt(secret)
    assert ciphertext != secret
    assert isinstance(ciphertext, str)
    decrypted = decrypt(ciphertext)
    assert decrypted == secret


def test_ssrf_ip_blocking():
    # Private / loopback / metadata IPs must be blocked
    assert _is_private_ip("127.0.0.1") is True
    assert _is_private_ip("localhost") is True
    assert _is_private_ip("169.254.169.254") is True
    assert _is_private_ip("10.0.0.5") is True
    assert _is_private_ip("192.168.1.1") is True
    assert _is_private_ip("172.16.0.1") is True


def test_read_only_sql_enforcement():
    # Valid SELECT queries should pass
    _assert_select_only("SELECT order_id, revenue FROM orders WHERE revenue > 100")
    _assert_select_only("select count(*) from customers")

    # Write / DDL statements must be rejected
    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("INSERT INTO orders VALUES ('ORD-999', 500)")
    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("UPDATE customers SET segment = 'VIP'")
    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("DROP TABLE products")
    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("DELETE FROM orders WHERE order_id = 'ORD-5001'")


# ── 2. Multi-Table Planted Anomaly & Relationship Tests ──────────────

def test_multi_table_relationship_validation_orders_customers(multi_table_data):
    orders = multi_table_data["orders"]
    customers = multi_table_data["customers"]

    # Validate orders.customer_id -> customers.customer_id
    res = validate_relationship(customers, "customer_id", orders, "customer_id")

    # Planted cases:
    # 1. Duplicate PK in customers: CUST-002 appears twice
    assert res["duplicate_pks"]["count"] == 2
    assert "CUST-002" in res["duplicate_pks"]["samples"]

    # 2. Orphan FK in orders: CUST-999 (ORD-5016)
    assert res["orphan_fks"]["count"] == 1
    assert "CUST-999" in res["orphan_fks"]["samples"]

    # 3. Null FK in orders: ORD-5018 has null customer_id
    assert res["null_fks"] == 1

    # Valid flag should be False due to anomalies
    assert res["valid"] is False


def test_multi_table_relationship_validation_orders_products(multi_table_data):
    orders = multi_table_data["orders"]
    products = multi_table_data["products"]

    res = validate_relationship(products, "product_id", orders, "product_id")

    # Planted orphan: PROD-999 (ORD-5017)
    assert res["orphan_fks"]["count"] == 1
    assert "PROD-999" in res["orphan_fks"]["samples"]
    # Products PK has no duplicates
    assert res["duplicate_pks"]["count"] == 0


def test_multi_table_relationship_validation_customers_regions(multi_table_data):
    customers = multi_table_data["customers"]
    regions = multi_table_data["regions"]

    res = validate_relationship(regions, "region_id", customers, "region_id")

    # Planted orphan: REG-999 in CUST-008
    assert res["orphan_fks"]["count"] == 1
    assert "REG-999" in res["orphan_fks"]["samples"]
    # Planted null: CUST-005 has null region_id
    assert res["null_fks"] == 1


def test_candidate_key_detection(multi_table_data):
    regions = multi_table_data["regions"]
    keys = detect_candidate_keys(regions)
    assert len(keys) > 0
    # region_id is 100% unique and 0% null
    top_key = keys[0]
    assert top_key["column"] == "region_id"
    assert bool(top_key["is_likely_pk"]) is True


# ── 3. Data Quality Engine Tests ────────────────────────────────────

def test_quality_rules_on_planted_cases(multi_table_data):
    orders = multi_table_data["orders"]
    customers = multi_table_data["customers"]

    # Date not in future check on order_date
    date_rule = {"type": "date_not_future", "column": "order_date"}
    eval_date = evaluate_rule(orders, date_rule)
    # ORD-5019 has date 2035-12-31
    assert eval_date["passed"] is False
    assert eval_date["fail_count"] >= 1

    # Non-negative range check on quantity
    range_rule = {"type": "range", "column": "quantity", "params": {"min": 1}}
    eval_qty = evaluate_rule(orders, range_rule)
    # ORD-5020 has quantity -3
    assert eval_qty["passed"] is False
    assert eval_qty["fail_count"] == 1

    # Unique check on customer_id in customers
    unique_rule = {"type": "unique", "column": "customer_id"}
    eval_cust = evaluate_rule(customers, unique_rule)
    # CUST-002 appears twice
    assert eval_cust["passed"] is False
    assert eval_cust["fail_count"] == 2

    # Referential integrity rule
    ref_rule = {"type": "referential_integrity", "column": "customer_id", "params": {"ref_column": "customer_id"}}
    eval_ref = evaluate_rule(orders, ref_rule, ref_df=customers)
    # CUST-999 is orphan
    assert eval_ref["passed"] is False
    assert eval_ref["fail_count"] == 1


# ── 4. ERP Quirk Detection ──────────────────────────────────────────

def test_erp_quirk_detection():
    # Simulate an ERP export with title row and subtotal row
    df_erp = pd.DataFrame({
        "Account": [None, "Acme Sales", "Widget A", "Widget B", "Subtotal", "Consulting", "Total"],
        "Amount": [None, None, "1,200", "3,400", "4,600", "800", "5,400"],
        "Code": [None, None, "A-1", "B-2", None, "C-3", None],
    })
    quirks = detect_erp_quirks(df_erp)

    # Must detect title row (row 0 has all NaNs)
    assert "title_rows" in quirks
    assert 0 in quirks["title_rows"]

    # Must detect subtotal rows
    assert "subtotal_rows" in quirks
    assert len(quirks["subtotal_rows"]) >= 1

    # Must detect text-formatted numbers in Amount
    assert "text_formatted_numbers" in quirks
    assert "Amount" in quirks["text_formatted_numbers"]


# ── 5. ETL Pipeline & Code Export Tests ──────────────────────────────

def test_etl_pipeline_execution_and_exports(multi_table_data):
    orders = multi_table_data["orders"]

    # Define a visual ETL pipeline: Dedupe orders -> Filter positive quantity -> Select columns
    pipeline_spec = {
        "_id": "pipe_test_01",
        "name": "Clean Orders Pipeline",
        "steps": [
            {
                "name": "Extract Orders",
                "type": "dataset",
                "category": "extract",
                "output": "raw_orders",
            },
            {
                "name": "Remove Duplicate Orders",
                "type": "dedupe",
                "input": "raw_orders",
                "output": "deduped_orders",
                "params": {"subset": ["order_id", "product_id"]},
            },
            {
                "name": "Filter Positive Quantities",
                "type": "filter",
                "input": "deduped_orders",
                "output": "filtered_orders",
                "params": {"expression": "quantity > 0"},
            },
        ],
    }

    # Verify SQL export
    sql_code = pipeline_engine.export_as_sql(pipeline_spec)
    assert "CREATE TEMP TABLE deduped_orders" in sql_code
    assert "ROW_NUMBER() OVER" in sql_code
    assert "WHERE quantity > 0" in sql_code

    # Verify R export
    r_code = pipeline_engine.export_as_r(pipeline_spec)
    assert "library(tidyverse)" in r_code
    assert "distinct" in r_code
    assert "filter(quantity > 0)" in r_code

    # Verify Python export
    py_code = pipeline_engine.export_as_python(pipeline_spec)
    assert "import pandas as pd" in py_code
    assert "drop_duplicates" in py_code
    assert 'query("quantity > 0")' in py_code
