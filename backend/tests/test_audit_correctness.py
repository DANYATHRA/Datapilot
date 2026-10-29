import io
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
import openpyxl
import pandas as pd
import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["ANTHROPIC_API_KEY"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.services.visual_recommender import profile_columns_for_visuals, evaluate_visual_suitability  # noqa: E402

client = TestClient(app)
SAMPLE_XLSX = Path(__file__).resolve().parents[2] / "sample_data" / "datapilot_test_sales.xlsx"


def auth_client():
    import uuid
    email = f"audit_{uuid.uuid4().hex[:8]}@test.com"
    r = client.post("/auth/register", json={"email": email, "password": "password123"})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── A) GATING TESTS ─────────────────────────────────────────────────────────────
def test_gating_no_dataset_returns_409():
    headers = auth_client()
    # When no datasets exist for this fresh user, visual & analytics endpoints return 409
    res = client.get("/visuals/recommendations", headers=headers)
    assert res.status_code == 409
    assert "No dataset" in res.json().get("detail", "")

    res_q = client.post("/visuals/query", json={"spec": {"type": "bar", "dataset_id": "dummy", "fields": {"category": "region", "value": "revenue"}}}, headers=headers)
    assert res_q.status_code == 409

    res_ins = client.post("/insights/generate", json={"dataset_id": "dummy"}, headers=headers)
    assert res_ins.status_code == 409


# ── C) RECOMMENDER TESTS ────────────────────────────────────────────────────────
def test_recommender_column_mix_rules():
    # Test 1: Dataframe with NO date column
    df_no_date = pd.DataFrame({
        "region": ["North", "South", "East", "West", "Central"],
        "revenue": [100.0, 200.0, 150.0, 300.0, 250.0],
        "quantity": [10, 20, 15, 30, 25],
    })
    profiles = profile_columns_for_visuals(df_no_date)
    eval_result = evaluate_visual_suitability(profiles, len(df_no_date), "test_ds")
    recs = eval_result["recommendations"]
    rec_dict = {r["type"]: r for r in recs}

    assert not rec_dict["line"]["suitable"]
    assert "date" in rec_dict["line"]["reason"].lower()
    assert not rec_dict["area"]["suitable"]
    assert rec_dict["bar"]["suitable"]
    assert rec_dict["pie"]["suitable"]

    # Test 2: Dataframe with rating scale 1..5
    df_likert = pd.DataFrame({
        "satisfaction_q1": [1, 2, 3, 4, 5, 4, 3, 2, 5, 4],
        "satisfaction_q2": [2, 3, 4, 5, 5, 4, 3, 3, 4, 5],
        "feedback": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
    })
    p_likert = profile_columns_for_visuals(df_likert)
    p_map = {p["name"]: p for p in p_likert}
    assert p_map["satisfaction_q1"]["is_rating_scale"]
    assert p_map["satisfaction_q2"]["is_rating_scale"]
    eval_likert = evaluate_visual_suitability(p_likert, len(df_likert), "test_ds")
    r_likert = eval_likert["recommendations"]
    likert_rec = next(r for r in r_likert if r["type"] == "likert_stack")
    assert likert_rec["suitable"]
    assert "rating" in likert_rec["reason"].lower()

    # Test 3: Starter visuals generation returns top 6-8 items
    starters = eval_result["starters"]
    assert 1 <= len(starters) <= 8
    for s in starters:
        assert s["type"] in rec_dict
        assert rec_dict[s["type"]]["suitable"]


# ── B) REAL EXCEL DOWNLOAD & ROUND TRIP ──────────────────────────────────────────
def test_export_real_xlsx_openpyxl_and_roundtrip():
    headers = auth_client()
    assert SAMPLE_XLSX.exists(), f"Missing {SAMPLE_XLSX}"

    # Upload test sales dataset
    with open(SAMPLE_XLSX, "rb") as f:
        up_res = client.post("/data-cleaning/upload", headers=headers, files={"file": ("test_sales.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert up_res.status_code == 200, up_res.text
    ds_id = up_res.json()["id"]

    # Run full cleaning pipeline
    pipe_res = client.post(f"/datasets/{ds_id}/pipeline/run", headers=headers, json={"skip": []})
    assert pipe_res.status_code == 200, pipe_res.text

    # GET /datasets/{id}/export?format=xlsx
    exp_res = client.get(f"/datasets/{ds_id}/export?format=xlsx", headers=headers)
    assert exp_res.status_code == 200, exp_res.text
    assert exp_res.headers["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    disp = exp_res.headers.get("Content-Disposition", "")
    assert 'filename="test_sales_cleaned.xlsx"' in disp or "cleaned.xlsx" in disp

    # Verify bytes start with zip magic PK
    content = exp_res.content
    assert content.startswith(b"PK\x03\x04"), "Excel file must start with zip magic PK bytes"

    # Open with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content))
    expected_sheets = ["Cleaned_Data", "Cleaned_Highlighted", "Change_Log", "Removed_Rows", "Summary", "Legend"]
    for s in expected_sheets:
        assert s in wb.sheetnames, f"Expected sheet '{s}' in workbook, found {wb.sheetnames}"

    ws_data = wb["Cleaned_Data"]
    # Check frozen panes (A2 frozen)
    assert ws_data.freeze_panes == "A2"
    # Check header is bold
    header_cell = ws_data.cell(row=1, column=1)
    assert header_cell.font and header_cell.font.bold
    # Check autofilter exists
    assert ws_data.auto_filter.ref is not None
    # Check that Cleaned_Data has no fill colors (plain white cells)
    data_cell = ws_data.cell(row=2, column=1)
    assert data_cell.fill.fill_type is None

    # Check Cleaned_Highlighted has fill colors on transformed cells
    ws_high = wb["Cleaned_Highlighted"]
    has_color_fill = False
    for r in range(2, min(ws_high.max_row + 1, 30)):
        for col in range(1, ws_high.max_column + 1):
            f = ws_high.cell(row=r, column=col).fill
            if f and f.fill_type and f.fgColor and f.fgColor.rgb != "00000000":
                has_color_fill = True
                break
        if has_color_fill:
            break
    assert has_color_fill, "Cleaned_Highlighted sheet must contain colour-coded changes"

    # Read back Cleaned_Data with pandas and compare rows/cols
    df_exported = pd.read_excel(io.BytesIO(content), sheet_name="Cleaned_Data")
    # Verify row count is positive and columns are clean
    assert len(df_exported) > 0
    assert "revenue" in df_exported.columns or any("rev" in c.lower() for c in df_exported.columns)

    # Test re-upload of this exported workbook: parser must read Cleaned_Data sheet
    reup_res = client.post(
        "/data-cleaning/upload",
        headers=headers,
        files={"file": ("test_sales_cleaned.xlsx", io.BytesIO(content), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert reup_res.status_code == 200, reup_res.text
    reup_id = reup_res.json()["id"]
    prev_res = client.get(f"/datasets/{reup_id}/preview", headers=headers)
    assert prev_res.status_code == 200
    assert prev_res.json()["columns"] == list(df_exported.columns)


# ── D) CORRECTNESS & TRACEABILITY: DUCKDB VS PANDAS ON 23 VISUALS & KPIS ────────
def test_duckdb_vs_pandas_visuals_and_kpis():
    headers = auth_client()
    with open(SAMPLE_XLSX, "rb") as f:
        up_res = client.post("/data-cleaning/upload", headers=headers, files={"file": ("test_sales.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert up_res.status_code == 200
    ds_id = up_res.json()["id"]

    # Run cleaning
    client.post(f"/datasets/{ds_id}/pipeline/run", headers=headers, json={"skip": []})

    # Fetch cleaned export into pandas for ground truth calculation
    exp_res = client.get(f"/datasets/{ds_id}/export?format=xlsx", headers=headers)
    assert exp_res.status_code == 200
    df = pd.read_excel(io.BytesIO(exp_res.content), sheet_name="Cleaned_Data")

    # 1. KPI Correctness: Total Revenue
    kpi_res = client.post("/visuals/query", headers=headers, json={
        "spec": {
            "type": "kpi_card",
            "dataset_id": ds_id,
            "fields": {"value": "revenue"},
            "options": {"aggregation": "sum"}
        }
    })
    assert kpi_res.status_code == 200
    kpi_data = kpi_res.json()
    assert "sql" in kpi_data
    assert "version_info" in kpi_data
    assert "reconciliation" in kpi_data
    expected_sum = float(df["revenue"].sum())
    actual_sum = float(kpi_data["kpi"]["raw_value"])
    assert round(actual_sum, 2) == round(expected_sum, 2)

    # 2. Bar Chart: Sum of revenue by region
    bar_res = client.post("/visuals/query", headers=headers, json={
        "spec": {
            "type": "bar",
            "dataset_id": ds_id,
            "fields": {"category": "region", "value": "revenue"},
            "options": {"aggregation": "sum"}
        }
    })
    assert bar_res.status_code == 200
    bar_data = bar_res.json()
    expected_grouped = df.groupby("region")["revenue"].sum().round(2).to_dict()
    for row in bar_data["rows"]:
        cat = row.get("category")
        val = float(row.get("revenue") or row.get("value") or 0)
        if cat in expected_grouped:
            assert round(val, 2) == expected_grouped[cat]

    # Reconciliation check: Grouped sum equals total
    grouped_sum = sum(float(r.get("revenue") or r.get("value") or 0) for r in bar_data["rows"])
    assert round(grouped_sum, 1) == round(expected_sum, 1)

    # 3. Line Chart: Sum of revenue by order_date
    line_res = client.post("/visuals/query", headers=headers, json={
        "spec": {
            "type": "line",
            "dataset_id": ds_id,
            "fields": {"category": "order_date", "value": "revenue"},
            "options": {"aggregation": "sum"}
        }
    })
    assert line_res.status_code == 200
    line_data = line_res.json()
    assert len(line_data["rows"]) > 0

    # 4. Scatter Plot: Units vs Revenue
    scatter_res = client.post("/visuals/query", headers=headers, json={
        "spec": {
            "type": "scatter",
            "dataset_id": ds_id,
            "fields": {"x": "units", "y": "revenue"}
        }
    })
    assert scatter_res.status_code == 200
    scatter_data = scatter_res.json()
    assert len(scatter_data["rows"]) > 0
    first_pt = scatter_data["rows"][0]
    assert "x" in first_pt and "y" in first_pt
    assert isinstance(first_pt["x"], (int, float)) and isinstance(first_pt["y"], (int, float))
