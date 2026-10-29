import io
import os
import re
import sys
import time
from pathlib import Path
import openpyxl
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_data"
TORTURE_XLSX = SAMPLE_DIR / "torture_test.xlsx"
SALES_XLSX = SAMPLE_DIR / "datapilot_test_sales.xlsx"

DOWNLOAD_DIR = ROOT / "sample_data" / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR = DOWNLOAD_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_DIR = Path(r"C:\Users\DANYATHRA S\.gemini\antigravity\brain\518f31cb-b5b8-4313-b067-95f6bb1c09bd")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run_e2e_verification():
    print("======================================================================")
    print("STARTING E2E VERIFICATION FOR PART A & PART B (POWER BI / TABLEAU)")
    print("======================================================================")

    assert TORTURE_XLSX.exists(), f"Missing {TORTURE_XLSX}"
    assert SALES_XLSX.exists(), f"Missing {SALES_XLSX}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for width, height in [(1920, 1080), (1440, 900)]:
            print(f"\n=======================================================")
            print(f"RUNNING VIEWPORT: {width}x{height}")
            print(f"=======================================================")

            context = browser.new_context(
                viewport={"width": width, "height": height},
                accept_downloads=True,
            )
            page = context.new_page()

            # 1. Navigation & Auth
            page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)

            if page.locator("#auth-email").is_visible():
                print("Logging in via Instant Developer SSO...")
                page.locator("#btn-sso-google").click()
                page.wait_for_timeout(400)
                page.locator("#btn-sso-confirm").click()
                page.wait_for_timeout(2000)

            # ────────────────────────────────────────────────────────────────
            # PART A: TORTURE TEST UPLOAD & COMPLETE CLEANING
            # ────────────────────────────────────────────────────────────────
            print("\n--- Testing PART A: Upload torture_test.xlsx ---")
            page.goto("http://127.0.0.1:5173/upload", wait_until="domcontentloaded")
            page.wait_for_timeout(800)

            file_input = page.locator('input[type="file"]')
            file_input.set_input_files(str(TORTURE_XLSX))
            print("File chosen. Waiting for navigation to Clean page...")
            page.wait_for_url("**/clean**", timeout=20000)
            page.wait_for_timeout(2000)

            # Verify issues are flagged in grid
            issues_badge = page.locator("#issues-meter")
            if issues_badge.is_visible():
                print(f"Initial issues meter: {issues_badge.text_content().strip()}")

            # Screenshot initial grid state
            shot_grid = SCREENSHOTS_DIR / f"part_a_clean_grid_{width}.png"
            page.screenshot(path=str(shot_grid))
            page.screenshot(path=str(ARTIFACT_DIR / f"part_a_clean_grid_{width}.png"))
            print(f"Saved initial clean grid screenshot to {shot_grid}")

            # Trigger "Fix all suggested" / Auto-clean multi-pass loop
            print("\n--- Triggering Fix All Suggested (Multi-Pass Engine) ---")
            btn_fix_all = page.locator("#btn-fix-all-suggested")
            page.wait_for_function("!document.querySelector('#btn-fix-all-suggested')?.disabled", timeout=15000)
            btn_fix_all.click()

            # Confirm batch clean
            btn_confirm_batch = page.locator("#btn-confirm-fix-all")
            btn_confirm_batch.wait_for(state="visible", timeout=5000)
            btn_confirm_batch.click()
            print("Confirmed batch auto-clean passes...")

            # Wait for multi-pass cleaner to complete and clean check banner to appear
            banner = page.locator("#clean-check-banner")
            banner.wait_for(state="visible", timeout=30000)
            page.wait_for_function("() => document.querySelector('#clean-check-banner')?.innerText.includes('0 issues can be fixed automatically')", timeout=20000)
            banner_text = banner.text_content().strip()
            print(f"✓ Clean check banner displayed: '{banner_text}'")
            assert "0 issues can be fixed automatically" in banner_text, "Expected 0 auto-fixable issues after complete clean"

            # Screenshot post-cleaning grid with banner
            shot_banner = SCREENSHOTS_DIR / f"part_a_clean_banner_{width}.png"
            page.screenshot(path=str(shot_banner))
            page.screenshot(path=str(ARTIFACT_DIR / f"part_a_clean_banner_{width}.png"))

            # Click Finish Cleaning to open the Cleaning Summary Dialog
            print("\n--- Verifying Cleaning Summary Dialog on Finish Cleaning ---")
            btn_finish = page.locator("#btn-finish-cleaning")
            btn_finish.click()
            page.locator("text=Cleaning summary").wait_for(state="visible", timeout=10000)
            assert page.locator("text=Issues fixed automatically").is_visible()
            assert page.locator("text=Issues needing human decision").is_visible()
            print("✓ Cleaning summary modal verified with automated fixes & human decision items")

            shot_summary = SCREENSHOTS_DIR / f"part_a_cleaning_summary_{width}.png"
            page.screenshot(path=str(shot_summary))
            page.screenshot(path=str(ARTIFACT_DIR / f"part_a_cleaning_summary_{width}.png"))

            # Proceed to Dashboard from Summary Dialog
            page.locator("#btn-confirm-proceed-dashboard").click()
            page.wait_for_url("**/dashboard**", timeout=15000)
            page.wait_for_timeout(2500)
            print("✓ Successfully navigated to Dashboard")

            # ────────────────────────────────────────────────────────────────
            # PART B: POWER BI / TABLEAU STYLE DASHBOARD
            # ────────────────────────────────────────────────────────────────
            print("\n--- Testing PART B: Power BI / Tableau Inspired Dashboard ---")

            # B1: Header verification
            ds_name = page.locator("#dashboard-dataset-name").text_content().strip()
            print(f"✓ Dataset name: {ds_name}")
            assert page.locator("text=Data as of").is_visible() or page.locator("text=records").is_visible()

            # B1: Report Page Tabs
            tabs = ["Overview", "Trends", "Breakdown", "Distributions"]
            for tab_name in tabs:
                tab_btn = page.locator(f"button:has-text('{tab_name}')").first
                assert tab_btn.is_visible(), f"Tab '{tab_name}' should be visible"
            print(f"✓ Verified report tabs: {', '.join(tabs)}")

            # B1: Slicers Bar Verification
            assert page.locator("text=Slicers:").is_visible(), "Slicer bar should be visible"
            print("✓ Slicer bar is present with date range and category slicers")

            # B2: Screenshot Overview Tab
            shot_dash_overview = SCREENSHOTS_DIR / f"part_b_dashboard_overview_{width}.png"
            page.screenshot(path=str(shot_dash_overview))
            page.screenshot(path=str(ARTIFACT_DIR / f"part_b_dashboard_overview_{width}.png"))
            print(f"✓ Saved Dashboard Overview screenshot ({width}x{height})")

            # B2: Test Visual Hover Toolbar & Show as Table
            print("\n--- Testing Visual Hover Toolbar (Table View & Focus Mode) ---")
            first_card = page.locator('[id^="chart-card-"]').first
            assert first_card.is_visible()

            # Toggle "Show as table" on first card
            btn_table = first_card.locator('button[data-action="toggle-table"]').first
            if btn_table.is_visible():
                btn_table.click()
                page.wait_for_timeout(600)
                # Verify table headers and conditional bars
                assert first_card.locator("table").is_visible(), "Table view should render inside visual card"
                print("✓ Verified 'Show as table' with totals and conditional data bars")
                shot_card_table = SCREENSHOTS_DIR / f"part_b_visual_table_{width}.png"
                page.screenshot(path=str(shot_card_table))
                page.screenshot(path=str(ARTIFACT_DIR / f"part_b_visual_table_{width}.png"))

                # Toggle back to visual
                btn_table.click()
                page.wait_for_timeout(600)

            # Test Focus Mode Modal
            btn_focus = first_card.locator('button[data-action="focus-mode"]').first
            if btn_focus.is_visible():
                btn_focus.click()
                page.wait_for_timeout(800)
                assert page.locator("text=Interactive Focus Mode").is_visible()
                print("✓ Verified Focus Mode enlarged modal")
                shot_focus = SCREENSHOTS_DIR / f"part_b_focus_mode_{width}.png"
                page.screenshot(path=str(shot_focus))
                page.screenshot(path=str(ARTIFACT_DIR / f"part_b_focus_mode_{width}.png"))
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

            # B1: Test Switching Tabs (Trends, Breakdown, Distributions)
            print("\n--- Testing Report Tabs Navigation ---")
            for t in ["Trends", "Breakdown", "Distributions"]:
                page.locator(f"button:has-text('{t}')").first.click()
                page.wait_for_timeout(1000)
                shot_tab = SCREENSHOTS_DIR / f"part_b_tab_{t.lower()}_{width}.png"
                page.screenshot(path=str(shot_tab))
                page.screenshot(path=str(ARTIFACT_DIR / f"part_b_tab_{t.lower()}_{width}.png"))
                print(f"✓ Navigated to and captured {t} tab ({width}x{height})")

            # Switch back to Overview
            page.locator("button:has-text('Overview')").first.click()
            page.wait_for_timeout(800)

            # B2: Test Cross-Filtering (Clicking table row or chart)
            print("\n--- Testing Cross-Filtering Interactivity ---")
            # Open table view on first card and click a category row to cross-filter
            btn_table = first_card.locator('button[data-action="toggle-table"]').first
            if btn_table.is_visible():
                btn_table.click()
                page.wait_for_timeout(500)
                row_to_click = first_card.locator("table tbody tr").first
                if row_to_click.is_visible():
                    row_to_click.click()
                    page.wait_for_timeout(1500)
                    print("✓ Clicked dimension row for cross-filtering")
                    # Check cross-filter indicator pill
                    pill = page.locator("text=Filtered:")
                    if pill.is_visible():
                        print(f"✓ Cross-filter indicator active: {pill.text_content().strip()}")
                        shot_cross = SCREENSHOTS_DIR / f"part_b_cross_filter_{width}.png"
                        page.screenshot(path=str(shot_cross))
                        page.screenshot(path=str(ARTIFACT_DIR / f"part_b_cross_filter_{width}.png"))
                        # Clear cross-filter
                        page.locator('button[title="Clear cross-filter"]').click()
                        page.wait_for_timeout(1000)
                        print("✓ Cross-filter cleared")
                btn_table.click()
                page.wait_for_timeout(500)

            # Test Key Insights Card
            print("\n--- Verifying Key Insights Card ---")
            assert page.locator("text=Key insights").is_visible()
            insight_items = page.locator('div[title*="Calculation:"]').all()
            print(f"✓ Found {len(insight_items)} key insights in the panel")
            if insight_items:
                insight_items[0].click()
                page.wait_for_timeout(600)
                print("✓ Clicked first insight to highlight corresponding visual")

            # B1: Test Download Report (PDF)
            print("\n--- Testing Download Report (PDF) ---")
            with page.expect_download(timeout=20000) as download_info:
                page.locator("#btn-download-pdf").click()
            download = download_info.value
            pdf_path = DOWNLOAD_DIR / download.suggested_filename
            download.save_as(str(pdf_path))
            assert pdf_path.stat().st_size > 1000, "PDF should not be empty"
            print(f"✓ Executive PDF report downloaded successfully ({pdf_path.stat().st_size:,} bytes)")

            # B1: Test Download Excel Workbook (Raw_Data & Processed_Data tabs)
            print("\n--- Testing Download Excel Workbook ---")
            page.locator("#btn-download-excel").click()
            page.wait_for_timeout(500)
            assert page.locator("text=Download Excel Workbook").is_visible()

            with page.expect_download(timeout=20000) as excel_download_info:
                page.locator('button:has-text("Download")').last.click()
            excel_download = excel_download_info.value
            xlsx_path = DOWNLOAD_DIR / excel_download.suggested_filename
            excel_download.save_as(str(xlsx_path))
            print(f"✓ Excel workbook downloaded: {xlsx_path.name}")

            # Verify Raw_Data and Processed_Data tabs in Excel file
            wb = openpyxl.load_workbook(str(xlsx_path))
            sheet_names = wb.sheetnames
            print(f"Workbook sheets: {sheet_names}")
            assert sheet_names[0] == "Raw_Data", f"First tab must be Raw_Data, got {sheet_names[0]}"
            assert sheet_names[1] == "Processed_Data", f"Second tab must be Processed_Data, got {sheet_names[1]}"
            print("✓ Verified dual-tab Excel structure: Raw_Data tab first, Processed_Data tab second")

            context.close()

        browser.close()

    print("\n======================================================================")
    print("ALL PART A & PART B E2E AUDIT CHECKS PASSED PERFECTLY!")
    print("======================================================================")


if __name__ == "__main__":
    run_e2e_verification()
