"""
Independent Unit & Regression Tests for Complete Cleaning (Contract A1, A2, A3).
Cross-checked with independent pandas assertions.
"""
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

import sys
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.complete_cleaner import (
    run_multi_pass_auto_clean,
    run_clean_check,
    is_missing_value,
    clean_structure_preamble_and_headers,
    clean_structure_rows_and_cols,
    standardize_missing_tokens_in_df,
    normalize_text_in_df,
    clean_and_convert_numbers,
    clean_and_standardize_dates,
    clean_and_standardize_categories,
    clean_identifiers_and_contacts,
    clean_rows_and_duplicates,
    clean_missing_values_semantic,
)
from app.services.parser import parse_excel
from app.services.column_semantics import infer_dataset_semantics

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"
TORTURE_XLSX = SAMPLE_DIR / "torture_test.xlsx"
SALES_XLSX = SAMPLE_DIR / "datapilot_test_sales.xlsx"
STUDENTS_XLSX = SAMPLE_DIR / "students.xlsx"


def test_torture_fixture_full_cleaning_and_zero_autofixable():
    """A1 & A2: Multi-pass cleaning eliminates ALL auto-fixable issues on torture test."""
    assert TORTURE_XLSX.exists(), "Missing torture_test.xlsx"
    raw_bytes = TORTURE_XLSX.read_bytes()
    df_parsed, meta = parse_excel(raw_bytes, "torture_test.xlsx")

    # Preamble rows (rows 1-2) should have been cleanly stripped by parser/preamble cleaner
    assert "order_id" in df_parsed.columns, f"Header not found: {df_parsed.columns}"

    # Run multi-pass auto clean
    cleaned_df, all_changes, removed_rows, passes = run_multi_pass_auto_clean(df_parsed, max_passes=5)
    assert passes <= 5
    assert len(all_changes) > 0, "Expected multiple auto-fixes across passes"

    # Run Clean Check
    check = run_clean_check(cleaned_df)
    assert check["status"] == "Clean"
    assert check["auto_fixable_count"] == 0, f"Auto-fixable issues remain: {check['auto_fixable_count']}"
    assert check["is_regression_free"] is True
    assert "Clean. 0 issues can be fixed automatically." in check["banner_message"]

    # Decision items must exist for true human choices
    decision_types = {d["issue_type"] for d in check["decision_items"]}
    # Blank ID, conflicting duplicate ID, invalid PAN/email, outlier, impossible value
    assert "missing_restricted" in decision_types or "conflicting_duplicate_id" in decision_types or "impossible_value" in decision_types

    # ── Independent Pandas Assertions ──
    # 1. No exact duplicates remain
    assert cleaned_df.duplicated().sum() == 0

    # 2. No missing-value tokens remain in text
    for col in cleaned_df.columns:
        s_vals = cleaned_df[col].dropna().astype(str).str.strip().str.lower()
        assert not s_vals.isin(["n/a", "#n/a", "null", "none", "tbd", "?", "#value!"]).any()

    # 3. Numeric columns are clean numeric
    for col in ["units", "unit_price", "total_amount"]:
        if col in cleaned_df.columns:
            num_s = pd.to_numeric(cleaned_df[col], errors="coerce")
            non_nulls = cleaned_df[col].dropna()
            # Non-null values should be numeric (except documented impossible negatives like -500 that need decision)
            assert num_s.notna().sum() >= len(non_nulls) * 0.9

    # 4. Text columns have no mojibake or curly quotes
    for col in cleaned_df.columns:
        for val in cleaned_df[col].dropna():
            if isinstance(val, str):
                assert "â€™" not in val
                assert "\u201c" not in val
                assert "\u201d" not in val

    # 5. Identifiers are preserved as strings
    if "order_id" in cleaned_df.columns:
        # Padded leading zero check (e.g. 105 -> 00105)
        id_lens = [len(str(v)) for v in cleaned_df["order_id"].dropna() if str(v) != ""]
        assert all(l == 5 for l in id_lens if l > 0)


def test_cleaner_is_idempotent():
    """A3: Running the cleaner a second time produces 0 changes (idempotency)."""
    raw_bytes = TORTURE_XLSX.read_bytes()
    df_parsed, _ = parse_excel(raw_bytes, "torture_test.xlsx")

    # Run pass 1
    cleaned_v1, changes_v1, _, _ = run_multi_pass_auto_clean(df_parsed, max_passes=5)

    # Run pass 2 on cleaned_v1
    cleaned_v2, changes_v2, removed_v2, passes_v2 = run_multi_pass_auto_clean(cleaned_v1, max_passes=5)

    # Second run must produce 0 changes
    assert len(changes_v2) == 0, f"Expected 0 changes on second run, got {len(changes_v2)}: {changes_v2[:3]}"
    assert len(removed_v2) == 0
    assert passes_v2 == 1  # exited immediately on first pass due to 0 changes
    pd.testing.assert_frame_equal(cleaned_v1, cleaned_v2)


def test_clean_sales_and_students_datasets():
    """Runs cleaner on existing sales and student datasets asserting 0 auto-fixable issues."""
    for path in [SALES_XLSX, STUDENTS_XLSX]:
        if path.exists():
            raw = path.read_bytes()
            df, _ = parse_excel(raw, path.name)
            cleaned, changes, _, _ = run_multi_pass_auto_clean(df, max_passes=5)
            check = run_clean_check(cleaned)
            assert check["auto_fixable_count"] == 0, f"Failed for {path.name}: {check['auto_fixable_count']} issues remain"
            assert check["status"] == "Clean"


def test_unit_detectors_and_fixers():
    """Unit tests for individual detectors and fixers."""
    # 1. Number cleaner: currency, commas, percentages, brackets, units
    df_num = pd.DataFrame({
        "amt": ["₹ 1,500.50", "(200)", "150-", "12%", "5 kg", "1.23e+02", "42.0"]
    })
    cleaned_num, num_changes = clean_and_convert_numbers(df_num, {"amt": {"semantic_type": "money_amount"}})
    assert float(cleaned_num.at[0, "amt"]) == 1500.50
    assert float(cleaned_num.at[1, "amt"]) == -200.0
    assert float(cleaned_num.at[2, "amt"]) == -150.0
    assert float(cleaned_num.at[3, "amt"]) == 0.12
    assert float(cleaned_num.at[4, "amt"]) == 5.0
    assert float(cleaned_num.at[5, "amt"]) == 123.0
    assert int(cleaned_num.at[6, "amt"]) == 42

    # 2. Text normalizer: whitespace, mojibake, curly quotes
    df_txt = pd.DataFrame({
        "cat": ["  Acme\u00a0Corp\u200b  ", "High    Priority", "Bobâ€™s", "“Special”", "Electronics,"]
    })
    cleaned_txt, txt_changes = normalize_text_in_df(df_txt, {"cat": {"semantic_type": "category"}})
    assert cleaned_txt.at[0, "cat"] == "Acme Corp"
    assert cleaned_txt.at[1, "cat"] == "High Priority"
    assert cleaned_txt.at[2, "cat"] == "Bob's"
    assert cleaned_txt.at[3, "cat"] == '"Special"'
    assert cleaned_txt.at[4, "cat"] == "Electronics"

    # 3. Category: boolean synonyms & fuzzy typos
    df_cat = pd.DataFrame({
        "flag": ["yes", "true", "1", "no", "0", "false"],
        "city": ["Bangalore", "Banglaore", "Bangalore", "Delhi", "Delhy", "Delhi"]
    })
    cleaned_cat, cat_changes = clean_and_standardize_categories(
        df_cat,
        {"flag": {"semantic_type": "status/boolean_flag"}, "city": {"semantic_type": "category"}}
    )
    assert (cleaned_cat["flag"].isin(["True", "False"])).all()
    # Fuzzy typo "Banglaore" should be merged to "Bangalore"
    assert "Banglaore" not in cleaned_cat["city"].values
    assert "Delhy" not in cleaned_cat["city"].values

    # 4. Contacts: phone formatting, email lowercasing
    df_contacts = pd.DataFrame({
        "phone": ["09876543210", "+91-98765-43210"],
        "email": [" John.DOE@Example.com ", "alice@test.org"]
    })
    cleaned_con, con_changes, _ = clean_identifiers_and_contacts(
        df_contacts,
        {"phone": {"semantic_type": "contact_phone"}, "email": {"semantic_type": "contact_email"}}
    )
    assert cleaned_con.at[0, "phone"] == "+91 98765 43210"
    assert cleaned_con.at[1, "phone"] == "+91 98765 43210"
    assert cleaned_con.at[0, "email"] == "john.doe@example.com"
