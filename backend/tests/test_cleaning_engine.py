import io
import json
import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
import numpy as np
import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import cleaning_engine, parser

client = TestClient(app)


def auth_header(email_prefix="cleaner"):
    import uuid
    email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "Password123!"})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"email": email, "password": "Password123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── Parser Tests ─────────────────────────────────────────────────────────────

def test_parse_csv_delimiters_and_encodings():
    # Semicolon delimited with UTF-8 BOM
    csv_content = "\ufeffid;code;name;price\n1;00123;Widget A;€12.50\n2;00456;Widget B;€20.00\n"
    df, meta = parser.parse_uploaded_file("products.csv", csv_content.encode("utf-8-sig"))
    assert len(df) == 2
    assert meta["delimiter"] == ";"
    assert meta["encoding"] == "utf-8-sig"
    # Verify leading zeros preserved
    assert str(df["code"].iloc[0]) == "00123"
    assert str(df["code"].iloc[1]) == "00456"

    # Tab delimited with Latin-1 encoding
    tab_content = "emp_id\tdepartment\tsalary\n007\tFinance\t5000\n008\tEngineering\t6000\n"
    df_tab, meta_tab = parser.parse_uploaded_file("emp.txt", tab_content.encode("latin1"))
    assert len(df_tab) == 2
    assert meta_tab["delimiter"] == "\t"
    assert str(df_tab["emp_id"].iloc[0]) == "007"


def test_parse_excel_with_sheets():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"x": [1, 2], "label": ["A", "B"]}).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame({"y": [10, 20, 30], "code": ["001", "002", "003"]}).to_excel(writer, sheet_name="Details", index=False)

    raw_excel = buf.getvalue()
    sheets = parser.list_excel_sheets(raw_excel, "test.xlsx")
    assert sheets == ["Summary", "Details"]

    # Parse specific sheet
    df_details, meta = parser.parse_uploaded_file("test.xlsx", raw_excel, sheet_name="Details")
    assert len(df_details) == 3
    assert meta["sheet_name"] == "Details"
    assert str(df_details["code"].iloc[0]) == "001"


def test_parse_json_and_parquet():
    # JSON array
    json_bytes = json.dumps([
        {"id": "01", "val": 100},
        {"id": "02", "val": 200},
    ]).encode("utf-8")
    df_j, meta_j = parser.parse_uploaded_file("data.json", json_bytes)
    assert len(df_j) == 2
    assert str(df_j["id"].iloc[0]) == "01"

    # Malformed non-array JSON
    bad_json = b'{"status": "error", "code": 500}'
    with pytest.raises(Exception):
        parser.parse_uploaded_file("bad.json", bad_json)

    # Parquet
    buf_p = io.BytesIO()
    pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]}).to_parquet(buf_p, index=False)
    df_p, meta_p = parser.parse_uploaded_file("data.parquet", buf_p.getvalue())
    assert len(df_p) == 2
    assert meta_p["format"] == "parquet"


def test_empty_and_corrupt_files():
    with pytest.raises(Exception):
        parser.parse_uploaded_file("empty.csv", b"")
    with pytest.raises(Exception):
        parser.parse_uploaded_file("corrupt.parquet", b"PAR1not_a_valid_parquet_file")


# ── Cleaning Engine Unit Operations ──────────────────────────────────────────

def test_missing_values_operations():
    df = pd.DataFrame({
        "num": [10.0, np.nan, 30.0, np.nan, 50.0],
        "cat": ["Apple", "Banana", np.nan, "Apple", "N/A"],
        "code": ["001", "002", "003", None, "005"]
    })

    # Test custom null markers
    df_marked, meta = cleaning_engine.op_missing_values(df, {
        "action": "keep",
        "custom_null_markers": ["N/A"]
    })
    assert df_marked["cat"].isna().sum() == 2

    # Fill numeric with median
    df_filled, _ = cleaning_engine.op_missing_values(df, {
        "action": "fill_numeric",
        "columns": ["num"],
        "strategy": "median"
    })
    assert df_filled["num"].isna().sum() == 0
    assert df_filled["num"].iloc[1] == 30.0

    # Fill categorical with mode
    df_mode, _ = cleaning_engine.op_missing_values(df, {
        "action": "fill_categorical",
        "columns": ["cat"]
    })
    assert df_mode["cat"].isna().sum() == 0
    assert df_mode["cat"].iloc[2] == "Apple"

    # Drop rows
    df_dropped, _ = cleaning_engine.op_missing_values(df, {
        "action": "drop_rows",
        "columns": ["num"]
    })
    assert len(df_dropped) == 3


def test_duplicate_operations():
    df = pd.DataFrame({
        "id": [1, 2, 2, 3, 2],
        "val": ["A", "B", "B", "C", "D"]
    })
    # Exact duplicates: keep first
    df_exact, meta_exact = cleaning_engine.op_duplicates(df, {"action": "keep_first"})
    assert len(df_exact) == 4  # row 2 is identical to row 1

    # Key subset duplicate on 'id': keep first
    df_key, meta_key = cleaning_engine.op_duplicates(df, {"action": "keep_first", "subset": ["id"]})
    assert len(df_key) == 3
    assert set(df_key["id"]) == {1, 2, 3}

    # Key subset: remove all duplicates
    df_rem, _ = cleaning_engine.op_duplicates(df, {"action": "remove_all", "subset": ["id"]})
    assert len(df_rem) == 2  # Only id 1 and 3 are unique


def test_text_normalization_and_snake_case():
    df = pd.DataFrame({
        " First Name ": [" Alice ", "Bob  ", "  Charlie "],
        "Category!!": ["AI & DS", "AI and DS", "AI&DS"],
        "First Name": ["A", "B", "C"]  # duplicate after cleaning
    })
    # Snake case column names without collisions
    df_cols, meta_cols = cleaning_engine.op_text_normalization(df, {"action": "snake_case_columns"})
    assert "first_name" in df_cols.columns
    assert "first_name_1" in df_cols.columns or "first_name_2" in df_cols.columns
    assert "category" in df_cols.columns

    # Trim whitespace
    df_trim, _ = cleaning_engine.op_text_normalization(df, {"action": "trim_whitespace", "columns": [" First Name "]})
    assert df_trim[" First Name "].iloc[0] == "Alice"

    # Replace category near-duplicates
    df_cat, _ = cleaning_engine.op_text_normalization(df, {
        "action": "replace_values",
        "columns": ["Category!!"],
        "mapping": {"AI&DS": "AI & DS", "AI and DS": "AI & DS"}
    })
    assert (df_cat["Category!!"] == "AI & DS").all()


def test_type_conversion_and_currency():
    df = pd.DataFrame({
        "revenue": ["$1,200.50", "₹3,400.00", "(500.00)", "invalid"],
        "date_str": ["2025-01-15", "2025-02-20", "2025-03-25", "not_a_date"],
        "is_active": ["yes", "no", "true", "0"]
    })
    # Convert revenue to float with currency stripping
    df_rev, meta_rev = cleaning_engine.op_type_conversion(df, {
        "columns": ["revenue"],
        "target_type": "float",
        "strip_currency": True
    })
    assert df_rev["revenue"].iloc[0] == 1200.50
    assert df_rev["revenue"].iloc[1] == 3400.00
    assert df_rev["revenue"].iloc[2] == -500.00
    assert pd.isna(df_rev["revenue"].iloc[3])
    assert meta_rev["failed_conversions"]["revenue"] == 1

    # Convert date
    df_date, meta_date = cleaning_engine.op_type_conversion(df, {
        "columns": ["date_str"],
        "target_type": "datetime"
    })
    assert pd.api.types.is_datetime64_any_dtype(df_date["date_str"])
    assert meta_date["failed_conversions"]["date_str"] == 1

    # Convert boolean
    df_bool, _ = cleaning_engine.op_type_conversion(df, {
        "columns": ["is_active"],
        "target_type": "boolean"
    })
    assert df_bool["is_active"].tolist() == [True, False, True, False]


def test_business_validation_rules():
    df = pd.DataFrame({
        "score": [95, 105, -5, 80],
        "email": ["valid@test.com", "not_an_email", "good@company.org", None]
    })
    # Numeric range rule [0, 100] with drop_rows
    df_val, meta_val = cleaning_engine.op_validation_rules(df, {
        "column": "score",
        "rule_type": "numeric_range",
        "min": 0,
        "max": 100,
        "action": "drop_rows"
    })
    assert len(df_val) == 2
    assert set(df_val["score"]) == {95, 80}

    # Email validation with replace
    df_email, meta_email = cleaning_engine.op_validation_rules(df, {
        "column": "email",
        "rule_type": "email",
        "action": "replace",
        "replacement_value": "INVALID"
    })
    assert df_email["email"].iloc[1] == "INVALID"
    assert df_email["email"].iloc[0] == "valid@test.com"


def test_outlier_detection_and_treatment():
    # Normal distribution with extreme outliers
    vals = [20, 21, 22, 20, 23, 21, 22, 19, 21, 20, 200, -100]
    df = pd.DataFrame({"metric": vals})

    # Flag only (default)
    df_flag, meta_flag = cleaning_engine.op_outliers(df, {
        "column": "metric",
        "method": "iqr",
        "action": "flag"
    })
    assert len(df_flag) == len(df)
    assert meta_flag["outliers_found"] == 2

    # Cap (winsorize)
    df_cap, meta_cap = cleaning_engine.op_outliers(df, {
        "column": "metric",
        "method": "iqr",
        "action": "cap"
    })
    assert df_cap["metric"].max() < 100
    assert df_cap["metric"].min() > 0

    # Drop rows
    df_drop, meta_drop = cleaning_engine.op_outliers(df, {
        "column": "metric",
        "method": "iqr",
        "action": "drop_rows"
    })
    assert len(df_drop) == len(df) - 2


# ── Full End-to-End API Workflow Tests ───────────────────────────────────────

def test_cleaning_api_full_workflow():
    h = auth_header()

    # 1. Upload CSV with dirty data
    csv_raw = (
        "id,customer_name,email,units,revenue\n"
        "1, Alice ,alice@work.com,10,$100.00\n"
        "2,Bob,bob@corp.org,20,$200.00\n"
        "2,Bob,bob@corp.org,20,$200.00\n"  # duplicate
        "3,Charlie,bad_email,-5,$300.00\n"   # invalid negative units, bad email
        "4,Diana,diana@test.com,,N/A\n"       # missing units, N/A revenue
    ).encode("utf-8")

    r_up = client.post("/data-cleaning/upload", headers=h, files={"file": ("sales_dirty.csv", csv_raw)})
    assert r_up.status_code == 200, r_up.text
    ds_id = r_up.json()["id"]

    # 2. Get Profile
    r_prof = client.get(f"/data-cleaning/{ds_id}/profile", headers=h)
    assert r_prof.status_code == 200
    prof = r_prof.json()
    assert prof["rows"] == 5
    assert prof["duplicate_rows"] == 1
    assert "memory_formatted" in prof

    # 3. Preview Recipe
    recipe = [
        {"op": "duplicates", "params": {"action": "keep_first"}},
        {"op": "text_normalization", "params": {"action": "trim_whitespace", "columns": ["customer_name"]}},
        {"op": "missing_values", "params": {"action": "fill_numeric", "columns": ["units"], "strategy": "median", "custom_null_markers": ["N/A"]}},
        {"op": "type_conversion", "params": {"columns": ["revenue"], "target_type": "float", "strip_currency": True}},
        {"op": "validation_rules", "params": {"column": "units", "rule_type": "non_negative", "action": "drop_rows"}},
    ]

    r_prev = client.post(f"/data-cleaning/{ds_id}/preview", headers=h, json={"steps": recipe})
    assert r_prev.status_code == 200
    prev = r_prev.json()
    assert prev["dry_run"] is True
    assert prev["summary"]["rows_after"] == 3  # 1 duplicate dropped, 1 negative units dropped
    assert len(prev["destructive_warnings"]) > 0

    # Verify original dataset is untouched!
    r_prof_after_prev = client.get(f"/data-cleaning/{ds_id}/profile?version=1", headers=h)
    assert r_prof_after_prev.json()["rows"] == 5

    # 4. Execute Clean
    r_clean = client.post(f"/data-cleaning/{ds_id}/clean", headers=h, json={"steps": recipe})
    assert r_clean.status_code == 200, r_clean.text
    clean_res = r_clean.json()
    assert clean_res["dry_run"] is False
    assert clean_res["version"] == 2
    assert clean_res["summary"]["rows_after"] == 3

    # 5. Get Cleaning Report
    r_rep = client.get(f"/data-cleaning/{ds_id}/report", headers=h)
    assert r_rep.status_code == 200
    rep = r_rep.json()
    assert rep["dataset_id"] == ds_id
    assert rep["summary"]["rows_before"] == 5
    assert rep["summary"]["rows_after"] == 3
    assert len(rep["operations_applied"]) == 5

    # 6. Download Cleaning Report as JSON file
    r_rep_file = client.get(f"/data-cleaning/{ds_id}/report?download=true", headers=h)
    assert r_rep_file.status_code == 200
    assert "attachment" in r_rep_file.headers.get("Content-Disposition", "")
    assert json.loads(r_rep_file.text)["dataset_id"] == ds_id

    # 7. Download Transformation Log as CSV file
    r_log_file = client.get(f"/data-cleaning/{ds_id}/log", headers=h)
    assert r_log_file.status_code == 200
    assert "attachment" in r_log_file.headers.get("Content-Disposition", "")
    log_lines = r_log_file.text.strip().splitlines()
    assert len(log_lines) >= 6  # header + 5 steps
    assert "order,operation,columns" in log_lines[0]

    # 8. Download Cleaned Data in all 4 supported formats: CSV, XLSX, JSON, Parquet
    # CSV download
    r_dl_csv = client.get(f"/data-cleaning/{ds_id}/download?format=csv", headers=h)
    assert r_dl_csv.status_code == 200
    assert "attachment" in r_dl_csv.headers.get("Content-Disposition", "")
    df_downloaded_csv = pd.read_csv(io.StringIO(r_dl_csv.text))
    assert len(df_downloaded_csv) == 3
    assert df_downloaded_csv["customer_name"].iloc[0] == "Alice"  # whitespace trimmed

    # Excel XLSX download
    r_dl_xlsx = client.get(f"/data-cleaning/{ds_id}/download?format=xlsx", headers=h)
    assert r_dl_xlsx.status_code == 200
    df_downloaded_xlsx = pd.read_excel(io.BytesIO(r_dl_xlsx.content))
    assert len(df_downloaded_xlsx) == 3

    # JSON download
    r_dl_json = client.get(f"/data-cleaning/{ds_id}/download?format=json", headers=h)
    assert r_dl_json.status_code == 200
    df_downloaded_json = pd.read_json(io.StringIO(r_dl_json.text))
    assert len(df_downloaded_json) == 3

    # Parquet download
    r_dl_parquet = client.get(f"/data-cleaning/{ds_id}/download?format=parquet", headers=h)
    assert r_dl_parquet.status_code == 200
    df_downloaded_parquet = pd.read_parquet(io.BytesIO(r_dl_parquet.content))
    assert len(df_downloaded_parquet) == 3


def test_tenant_isolation_on_cleaning():
    h_user1 = auth_header("user1")
    h_user2 = auth_header("user2")

    csv_data = b"col1,col2\n10,20\n30,40\n"
    r = client.post("/data-cleaning/upload", headers=h_user1, files={"file": ("u1_data.csv", csv_data)})
    ds_id = r.json()["id"]

    # User 2 tries to access user 1's dataset
    assert client.get(f"/data-cleaning/{ds_id}/profile", headers=h_user2).status_code == 404
    assert client.post(f"/data-cleaning/{ds_id}/clean", headers=h_user2, json={"step": {"op": "duplicates"}}).status_code == 404
    assert client.get(f"/data-cleaning/{ds_id}/download?format=csv", headers=h_user2).status_code == 404
    assert client.get(f"/data-cleaning/{ds_id}/report", headers=h_user2).status_code == 404
    assert client.get(f"/data-cleaning/{ds_id}/log", headers=h_user2).status_code == 404
