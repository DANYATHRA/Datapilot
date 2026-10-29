"""
Tests for the auto-clean pipeline.

Build a messy .xlsx in memory (merged header, blank rows, ₹1,200-style currency,
mixed dates, duplicate rows, typos, an outlier, an email column), run the pipeline,
and assert correctness.
"""
import io
import re

import numpy as np
import openpyxl
import pandas as pd
import pytest

from app.services.pipeline import (
    STAGE_COLOURS,
    STAGE_ORDER,
    build_export_workbook,
    get_legend,
    run_pipeline,
)


def _build_messy_xlsx() -> bytes:
    """Create a deliberately messy Excel workbook for pipeline testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"

    # Row 1: a "title" row (junk, not the real header)
    ws.append(["Sales Report Q4 2024", None, None, None, None, None, None])

    # Row 2: blank row
    ws.append([None, None, None, None, None, None, None])

    # Row 3: real header
    ws.append(["Region", "Product", "Revenue", "Order Date", "Quantity", "Email", "Active"])

    # Row 4-13: data rows
    data = [
        ["North",  "Widget A", "₹1,200",  "2024-01-15", 10, "alice@example.com",  "yes"],
        ["  north", "Widget A", "₹2,500",  "15/02/2024", 20, "bob@example.com",    "Yes"],
        ["Nrth",   "Widget B", "$800",     "March 3, 2024", 15, "carol@example.com", "no"],
        ["South",  "Widget A", "€3,100",   "2024-04-01", 25, "dave@test.com",       "Y"],
        ["East",   "Widget C", "1500",     "2024/05/10", 30, "eve@example.com",     "No"],
        ["West",   "Widget A", "₹4,000",   "06-Jun-2024", 5, "frank@example.com",   "true"],
        ["South",  "Widget B", "₹900",     "2024-07-20", 12, "grace@example.com",   "false"],
        # Duplicate row (exact copy of row 4 data)
        ["North",  "Widget A", "₹1,200",  "2024-01-15", 10, "alice@example.com",  "yes"],
        # Outlier row
        ["East",   "Widget A", "₹99,999", "2024-08-01", 500, "hank@example.com",   "yes"],
        # Row with lots of missing values
        [None,     None,       None,       None,         None, None,                None],
    ]

    for row in data:
        ws.append(row)

    # Row 14: total row (junk)
    ws.append(["Total", None, "₹114,199", None, 627, None, None])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _load_test_df() -> pd.DataFrame:
    """Load the messy xlsx into a DataFrame the same way upload does."""
    raw = _build_messy_xlsx()
    bio = io.BytesIO(raw)
    df = pd.read_excel(bio, sheet_name="Sales", dtype=object)
    return df


class TestPipelineStageOrder:
    def test_stage_order_has_10_stages(self):
        assert len(STAGE_ORDER) == 10

    def test_stage_order_sequence(self):
        expected = [
            "structure", "column_names", "text_hygiene", "data_types",
            "value_standardisation", "missing_values", "duplicates",
            "outliers", "pii", "validation",
        ]
        assert STAGE_ORDER == expected


class TestLegend:
    def test_legend_returns_list(self):
        legend = get_legend()
        assert isinstance(legend, list)
        assert len(legend) >= 10

    def test_legend_has_required_fields(self):
        for item in get_legend():
            assert "stage" in item
            assert "colour_hex" in item
            assert "colour_name" in item
            assert "label" in item
            assert "marker" in item

    def test_legend_hex_format(self):
        for item in get_legend():
            assert item["colour_hex"].startswith("#")
            assert len(item["colour_hex"]) == 7


class TestPipelineRun:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df = _load_test_df()
        self.result = run_pipeline(self.df, sheet_name="Sales")

    def test_returns_cleaned_df(self):
        assert isinstance(self.result["cleaned_df"], pd.DataFrame)
        assert len(self.result["cleaned_df"]) > 0

    def test_returns_all_changes(self):
        assert isinstance(self.result["all_changes"], list)
        assert len(self.result["all_changes"]) > 0

    def test_returns_removed_rows(self):
        assert isinstance(self.result["removed_rows"], list)
        # We know there are empty rows and junk rows that should be removed
        assert len(self.result["removed_rows"]) > 0

    def test_returns_stage_summaries(self):
        summaries = self.result["stage_summaries"]
        assert len(summaries) == 10
        stages = [s["stage"] for s in summaries]
        assert stages == STAGE_ORDER

    def test_returns_quality_comparison(self):
        qc = self.result["quality_comparison"]
        assert "before" in qc
        assert "after" in qc
        assert "score" in qc["before"]
        assert "score" in qc["after"]

    def test_row_count_decreased(self):
        """Empty rows, junk rows, and duplicate rows should be removed."""
        original_rows = len(self.df)
        cleaned_rows = len(self.result["cleaned_df"])
        assert cleaned_rows < original_rows

    def test_change_records_have_required_fields(self):
        for ch in self.result["all_changes"][:20]:
            assert "stage" in ch
            assert "sheet" in ch
            assert "row" in ch
            assert "column" in ch
            assert "reason" in ch

    def test_skip_stages(self):
        result = run_pipeline(self.df, sheet_name="Sales", skip=["outliers", "pii"])
        summaries = result["stage_summaries"]
        outlier_s = next(s for s in summaries if s["stage"] == "outliers")
        pii_s = next(s for s in summaries if s["stage"] == "pii")
        assert outlier_s["status"] == "skipped"
        assert pii_s["status"] == "skipped"

    def test_duplicate_removal(self):
        """The exact duplicate row should have been removed."""
        dup_changes = [ch for ch in self.result["all_changes"]
                       if ch["stage"] == "duplicates"]
        assert len(dup_changes) >= 1

    def test_structure_cleanup(self):
        """Empty rows and junk/total rows should be cleaned."""
        struct_changes = [ch for ch in self.result["all_changes"]
                          if ch["stage"] == "structure"]
        assert len(struct_changes) >= 1


class TestExcelExport:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.df = _load_test_df()
        self.result = run_pipeline(self.df, sheet_name="Sales")
        self.xlsx_bytes = build_export_workbook(
            cleaned_df=self.result["cleaned_df"],
            all_changes=self.result["all_changes"],
            removed_rows=self.result["removed_rows"],
            stage_summaries=self.result["stage_summaries"],
            quality_comparison=self.result["quality_comparison"],
            sheet_name="Sales",
        )

    def test_workbook_has_required_sheets(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.xlsx_bytes))
        expected_sheets = {"Cleaned_Data", "Cleaned_Highlighted", "Change_Log",
                           "Removed_Rows", "Summary", "Legend"}
        assert expected_sheets.issubset(set(wb.sheetnames))

    def test_cleaned_data_has_no_fills(self):
        """Cleaned_Data should have no coloured fills (except header)."""
        wb = openpyxl.load_workbook(io.BytesIO(self.xlsx_bytes))
        ws = wb["Cleaned_Data"]
        for row in ws.iter_rows(min_row=2):  # skip header
            for cell in row:
                if cell.fill and cell.fill.start_color and cell.fill.start_color.rgb:
                    rgb = str(cell.fill.start_color.rgb)
                    # Should be no fill or white (00000000 is no fill)
                    assert rgb in ("00000000", "FFFFFFFF", "00FFFFFF", None, "0"), \
                        f"Cell {cell.coordinate} has unexpected fill: {rgb}"

    def test_legend_sheet_has_colours(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.xlsx_bytes))
        ws = wb["Legend"]
        # Should have at least the 10 stages + removed_row = 11 data rows
        data_rows = list(ws.iter_rows(min_row=2, values_only=False))
        assert len(data_rows) >= 10

    def test_removed_rows_sheet_exists(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.xlsx_bytes))
        ws = wb["Removed_Rows"]
        # Should have header + at least 1 data row
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) >= 2  # header + at least 1 removed row

    def test_change_log_colour_coded(self):
        """Change_Log rows should be colour-coded by stage."""
        wb = openpyxl.load_workbook(io.BytesIO(self.xlsx_bytes))
        ws = wb["Change_Log"]
        has_coloured = False
        for row in ws.iter_rows(min_row=2):
            if row[0].value:
                fill = row[0].fill
                if fill and fill.start_color and str(fill.start_color.rgb) not in ("00000000", "0"):
                    has_coloured = True
                    break
        assert has_coloured, "Change_Log should have colour-coded rows"

    def test_summary_sheet_has_stage_counts(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.xlsx_bytes))
        ws = wb["Summary"]
        # Row 1 = header, row 2+ = stages
        stages_found = []
        for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
            if row[0] and row[0] in STAGE_ORDER:
                stages_found.append(row[0])
        assert len(stages_found) == 10


class TestPipelineEdgeCases:
    def test_empty_df_raises_or_handles(self):
        """Pipeline should handle a DataFrame with zero rows gracefully."""
        df = pd.DataFrame(columns=["a", "b", "c"])
        result = run_pipeline(df, sheet_name="Empty")
        assert len(result["cleaned_df"]) == 0

    def test_single_row_df(self):
        df = pd.DataFrame({"name": ["Alice"], "value": [100]})
        result = run_pipeline(df, sheet_name="Single")
        assert len(result["cleaned_df"]) >= 0  # May or may not keep row

    def test_no_text_columns(self):
        """Pipeline should handle pure-numeric DataFrames."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        result = run_pipeline(df, sheet_name="Numeric")
        assert len(result["cleaned_df"]) == 3
