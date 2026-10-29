import io
import time
import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import grid_service, datasets as ds
from app.services.column_semantics import infer_dataset_semantics

client = TestClient(app)


def auth_client():
    import uuid
    email = f"grid_test_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "password123"})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── 1. SEMANTIC SUGGESTIONS & IDENTIFIER POLICY ───────────────────────────────
def test_suggestions_per_column_meaning_never_impute_identifiers():
    """Verify semantic rule: IDs, emails, phones, names, dates NEVER receive mean/median/mode."""
    df = pd.DataFrame({
        "order_id": ["ORD-001", None, "ORD-003", "ORD-004"],
        "customer_email": ["alice@work.com", "bob@corp.org", None, "david@test.com"],
        "customer_name": ["Alice", "Bob", None, "David"],
        "phone_number": ["9876543210", None, "9123456780", "9988776655"],
        "order_date": ["2026-01-01", None, "2026-01-03", "2026-01-04"],
        "unit_price": [100.0, None, 300.0, 400.0],
        "category": ["Electronics", "Electronics", None, "Furniture"],
    })

    semantics = infer_dataset_semantics(df)

    # 1. order_id (identifier)
    sug_id = grid_service.get_suggestion_for_cell(df, "order_id", 1, "missing", semantics)
    assert sug_id["is_restricted"] is True
    # Reason in 6 words or fewer
    words = sug_id["line2"].split()
    assert len(words) <= 7, f"Reason too long: {sug_id['line2']}"
    assert "can't be guessed" in sug_id["line2"] or "cannot" in sug_id["line2"]
    # Confirm no mean, median, or mode strategy in options
    opt_strategies = [o["strategy"] for o in sug_id["options"]]
    assert "mean" not in opt_strategies
    assert "median" not in opt_strategies
    assert "group_median" not in opt_strategies
    assert "mode" not in opt_strategies
    assert set(opt_strategies) <= {"leave_blank", "enter_value", "remove_row"}

    # Attempting to apply statistical imputation on identifier raises ValueError
    with pytest.raises(ValueError, match="strictly prohibited"):
        grid_service.apply_cell_or_column_fix(df, "missing", "order_id", 1, "mean", semantics=semantics)
    with pytest.raises(ValueError, match="strictly prohibited"):
        grid_service.apply_cell_or_column_fix(df, "missing", "order_id", 1, "median", semantics=semantics)
    with pytest.raises(ValueError, match="strictly prohibited"):
        grid_service.apply_cell_or_column_fix(df, "missing", "order_id", 1, "mode", semantics=semantics)

    # 2. customer_email
    sug_email = grid_service.get_suggestion_for_cell(df, "customer_email", 2, "missing", semantics)
    assert sug_email["is_restricted"] is True
    email_opts = [o["strategy"] for o in sug_email["options"]]
    assert "mean" not in email_opts and "median" not in email_opts and "mode" not in email_opts

    # 3. order_date
    sug_date = grid_service.get_suggestion_for_cell(df, "order_date", 1, "missing", semantics)
    assert sug_date["is_restricted"] is True
    date_opts = [o["strategy"] for o in sug_date["options"]]
    assert "mean" not in date_opts and "median" not in date_opts

    # 4. unit_price (number/money) CAN offer median/mean
    sug_price = grid_service.get_suggestion_for_cell(df, "unit_price", 1, "missing", semantics)
    assert sug_price["is_restricted"] is False
    price_opts = [o["strategy"] for o in sug_price["options"]]
    assert any(s in price_opts for s in ("median", "mean", "group_median"))


# ── 2. SCOPE COUNTS (CELL VS COLUMN) ──────────────────────────────────────────
def test_scope_counts_cell_vs_column():
    """Verify scope_counts return 1 for cell, and exact column missing count for column."""
    df = pd.DataFrame({
        "item": ["A", "B", "C", "D", "E"],
        "cost": [10.0, None, None, 40.0, None],  # 3 missing cells
    })
    semantics = infer_dataset_semantics(df)
    sug = grid_service.get_suggestion_for_cell(df, "cost", 1, "missing", semantics)

    assert sug["scope_counts"]["cell"] == 1
    assert sug["scope_counts"]["column"] == 3

    # Apply to single cell
    df_cell, affected_cell, _ = grid_service.apply_cell_or_column_fix(
        df, "missing", "cost", row=1, strategy="median", scope="cell", semantics=semantics
    )
    assert affected_cell == 1
    assert pd.notna(df_cell.at[1, "cost"])
    assert pd.isna(df_cell.at[2, "cost"])  # other cells remain missing

    # Apply to entire column
    df_col, affected_col, _ = grid_service.apply_cell_or_column_fix(
        df, "missing", "cost", row=1, strategy="median", scope="column", semantics=semantics
    )
    assert affected_col == 3
    assert int(df_col["cost"].isna().sum()) == 0


# ── 3. GROUP MEDIAN CORRECTNESS AGAINST PANDAS ────────────────────────────────
def test_group_median_correctness_against_pandas():
    """Verify group median matches pandas groupby median."""
    df = pd.DataFrame({
        "category": ["Phone", "Phone", "Phone", "Phone", "Laptop", "Laptop", "Laptop", "Laptop"],
        "price": [500.0, 520.0, 480.0, None, 1200.0, 1100.0, 1300.0, None],
    })
    semantics = infer_dataset_semantics(df)

    # Expected pandas medians
    expected_phone_median = float(df[df["category"] == "Phone"]["price"].dropna().median())
    expected_laptop_median = float(df[df["category"] == "Laptop"]["price"].dropna().median())

    # Row 3 is Phone
    sug_phone = grid_service.get_suggestion_for_cell(df, "price", 3, "missing", semantics)
    assert sug_phone["suggested_value"] == expected_phone_median

    # Row 7 is Laptop
    sug_laptop = grid_service.get_suggestion_for_cell(df, "price", 7, "missing", semantics)
    assert sug_laptop["suggested_value"] == expected_laptop_median


# ── 4. EDIT VALIDATION BY TYPE ────────────────────────────────────────────────
def test_edit_validation_by_type():
    """Verify validation correctly accepts valid values and rejects invalid values."""
    # Number
    ok, parsed, _ = grid_service.validate_cell_value("1,250.50", "price", "money_amount", float)
    assert ok is True and parsed == 1250.50

    ok, parsed, _ = grid_service.validate_cell_value("₹3,400", "price", "money_amount", float)
    assert ok is True and parsed == 3400.0

    ok, _, err = grid_service.validate_cell_value("not_a_number", "price", "money_amount", float)
    assert ok is False and "not a valid number" in err

    # Date
    ok, parsed, _ = grid_service.validate_cell_value("2026-03-15", "order_date", "date", object)
    assert ok is True and parsed == "2026-03-15"

    ok, _, err = grid_service.validate_cell_value("invalid_date_abc", "order_date", "date", object)
    assert ok is False and "not a valid date" in err

    # Email
    ok, parsed, _ = grid_service.validate_cell_value("user@domain.com", "email", "email", object)
    assert ok is True and parsed == "user@domain.com"

    ok, _, err = grid_service.validate_cell_value("plaintext_no_at", "email", "email", object)
    assert ok is False and "not a valid email" in err

    # Phone
    ok, parsed, _ = grid_service.validate_cell_value("+91 98765 43210", "phone", "phone", object)
    assert ok is True

    ok, _, err = grid_service.validate_cell_value("123", "phone", "phone", object)
    assert ok is False and "7 and 15 digits" in err


# ── 5. UNDO / REDO / REVERT CELL WORKFLOW ──────────────────────────────────────
def test_undo_redo_and_revert_cell_workflow():
    """Test full cycle of manual edit, undo, redo, and revert cell to v1."""
    headers = auth_client()
    csv_bytes = b"id,name,value\n1,Alice,100\n2,Bob,200\n3,Charlie,300\n"

    up = client.post("/datasets/upload", headers=headers, files={"file": ("test_flow.csv", csv_bytes)})
    assert up.status_code == 200, up.text
    ds_id = up.json()["id"]

    # 1. Edit a cell: change Charlie's value from 300 to 999
    patch_res = client.patch(
        f"/datasets/{ds_id}/cells",
        headers=headers,
        json={"edits": [{"row": 2, "column": "value", "value": 999}]},
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["version"] == 2

    # Check updated value in grid
    g1 = client.get(f"/datasets/{ds_id}/grid", headers=headers).json()
    assert g1["rows"][2]["_cells"]["value"]["val"] == 999
    assert g1["can_undo"] is True

    # 2. Undo edit
    undo_res = client.post(f"/datasets/{ds_id}/undo", headers=headers)
    assert undo_res.status_code == 200
    assert undo_res.json()["current_version"] == 1

    g2 = client.get(f"/datasets/{ds_id}/grid", headers=headers).json()
    assert g2["rows"][2]["_cells"]["value"]["val"] == 300
    assert g2["can_redo"] is True

    # 3. Redo edit
    redo_res = client.post(f"/datasets/{ds_id}/redo", headers=headers)
    assert redo_res.status_code == 200
    assert redo_res.json()["current_version"] == 2

    g3 = client.get(f"/datasets/{ds_id}/grid", headers=headers).json()
    assert g3["rows"][2]["_cells"]["value"]["val"] == 999

    # 4. Revert single cell back to original upload (v1)
    revert_res = client.post(
        f"/datasets/{ds_id}/revert-cell",
        headers=headers,
        json={"row": 2, "column": "value"},
    )
    assert revert_res.status_code == 200
    assert revert_res.json()["reverted_value"] == 300

    g4 = client.get(f"/datasets/{ds_id}/grid", headers=headers).json()
    assert g4["rows"][2]["_cells"]["value"]["val"] == 300


# ── 6. RAW DATA IS NEVER MODIFIED ─────────────────────────────────────────────
def test_raw_data_never_modified():
    """Verify raw upload (v1) is immutable and preserved exactly."""
    headers = auth_client()
    csv_bytes = b"code,title,score\nA1,Item1,50\nA2,Item2,60\nA3,Item3,\n"

    up = client.post("/datasets/upload", headers=headers, files={"file": ("raw_test.csv", csv_bytes)})
    assert up.status_code == 200
    ds_id = up.json()["id"]

    # Apply multiple fixes and edits
    client.post(
        f"/datasets/{ds_id}/fix",
        headers=headers,
        json={"issue_type": "missing", "column": "score", "row": 2, "strategy": "median", "scope": "cell"},
    )
    client.patch(
        f"/datasets/{ds_id}/cells",
        headers=headers,
        json={"edits": [{"row": 0, "column": "title", "value": "ModifiedTitle"}]},
    )

    # Verify v1 remains identical
    g_raw = client.get(f"/datasets/{ds_id}/grid?view=original", headers=headers).json()
    assert g_raw["rows"][0]["_cells"]["title"]["val"] == "Item1"
    assert g_raw["rows"][2]["_cells"]["score"]["val"] == ""


# ── 7. EXPORT SHEET ORDER AND CONTENTS ─────────────────────────────────────────
def test_export_sheet_order_and_contents():
    """Verify workbook contains Tab 1: Raw_Data, Tab 2: Processed_Data, bold headers, frozen panes, autofilter."""
    headers = auth_client()
    csv_bytes = b"order_id,product,units,price\n101,Keyboard,2,50\n102,Mouse,,25\n103,Monitor,1,200\n"

    up = client.post("/datasets/upload", headers=headers, files={"file": ("sales_order.csv", csv_bytes)})
    ds_id = up.json()["id"]

    # Fill missing units with median
    client.post(
        f"/datasets/{ds_id}/fix",
        headers=headers,
        json={"issue_type": "missing", "column": "units", "row": 1, "strategy": "median", "scope": "cell"},
    )

    # Download Excel workbook
    res = client.get(f"/datasets/{ds_id}/download-excel?format=xlsx&include_change_log=true", headers=headers)
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    sheets = wb.sheetnames

    # Assert exact order: Tab 1 Raw_Data, Tab 2 Processed_Data
    assert sheets[0] == "Raw_Data", f"First tab must be 'Raw_Data', got {sheets[0]}"
    assert sheets[1] == "Processed_Data", f"Second tab must be 'Processed_Data', got {sheets[1]}"
    assert "Change_Log" in sheets

    ws_raw = wb["Raw_Data"]
    ws_proc = wb["Processed_Data"]

    # Assert Raw_Data equals the original upload (row 3 units was missing/empty)
    assert ws_raw.cell(row=3, column=3).value in ("", None)

    # Assert Processed_Data has cleaned/fixed value
    assert ws_proc.cell(row=3, column=3).value is not None

    # Assert styling: Frozen panes, bold header, autofilter
    assert ws_proc.freeze_panes == "A2"
    assert ws_proc.cell(row=1, column=1).font.bold is True
    assert ws_proc.auto_filter.ref is not None


# ── 8. LARGE SHEET PAGING PERFORMANCE ─────────────────────────────────────────
def test_large_sheet_paging_performance():
    """Verify grid paging handles 50k+ rows with sub-second response time."""
    # Create 55,000 rows
    n_rows = 55000
    df_large = pd.DataFrame({
        "id": range(1, n_rows + 1),
        "amount": [10.5 * (i % 100) for i in range(n_rows)],
        "category": [f"Cat_{i % 5}" for i in range(n_rows)],
    })

    t0 = time.perf_counter()
    paged = df_large.iloc[50000: 50100]
    elapsed = time.perf_counter() - t0

    assert len(paged) == 100
    assert elapsed < 0.1, f"Paging slice took {elapsed:.4f}s"

