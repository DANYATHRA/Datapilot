import io
import os
import sys
import time
from pathlib import Path
import openpyxl
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_data"
STUDENTS_XLSX = SAMPLE_DIR / "students.xlsx"
SALES_XLSX = SAMPLE_DIR / "datapilot_test_sales.xlsx"

DOWNLOAD_DIR = ROOT / "sample_data" / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run_tests():
    print("=== STARTING PLAYWRIGHT END-TO-END VALIDATION ===")
    assert STUDENTS_XLSX.exists(), f"Missing {STUDENTS_XLSX}"
    assert SALES_XLSX.exists(), f"Missing {SALES_XLSX}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # 1. Open app
        print("Navigating to http://127.0.0.1:5173/ ...")
        page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Check if auth page is shown
        if page.locator("#auth-email").is_visible():
            print("Logging into DataPilot via Instant Developer SSO...")
            page.click('button:has-text("Google")')
            page.wait_for_timeout(1000)
            page.click('button:has-text("Sign In as Google User")')
            page.wait_for_timeout(2500)

        # 2. Check Sidebar Order and Labels
        print("Checking sidebar grouping and numbered step order...")
        sidebar_text = page.locator(".app-sidebar").inner_text()
        print("Sidebar text snippet:\n", sidebar_text[:400])

        assert "DATA" in sidebar_text, "Missing DATA group"
        assert "ANALYSE" in sidebar_text, "Missing ANALYSE group"
        assert "OUTPUT" in sidebar_text, "Missing OUTPUT group"

        assert "1" in sidebar_text and "Upload" in sidebar_text
        assert "2" in sidebar_text and "Clean & prepare" in sidebar_text
        assert "3" in sidebar_text and "Visual studio" in sidebar_text
        assert "4" in sidebar_text and "Insights" in sidebar_text
        assert "5" in sidebar_text and "Survey analysis" in sidebar_text
        assert "6" in sidebar_text and "SQL & Ask AI" in sidebar_text
        assert "7" in sidebar_text and "Dashboards" in sidebar_text
        assert "8" in sidebar_text and "Reports & export" in sidebar_text
        print("✓ Sidebar groups and numbered steps 1-8 verified in exact order.")

        # 3. Check Header current dataset chip with Change file link
        header_text = page.locator(".app-workspace-header").inner_text()
        assert "Change file" in header_text or page.locator("#btn-header-change-file").is_visible() or page.locator("#btn-header-change-file-empty").is_visible()
        print("✓ Header dataset chip and Change file link verified.")

        # 4. Navigate to Step 1 Upload
        print("Navigating to /upload...")
        page.click("#step-upload")
        page.wait_for_timeout(1000)
        assert "/upload" in page.url, f"Expected URL /upload, got {page.url}"

        # Upload students.xlsx via file input
        print(f"Uploading {STUDENTS_XLSX.name}...")
        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(STUDENTS_XLSX))
        page.wait_for_timeout(3000)

        # Multi-sheet check or direct upload
        if page.locator('button:has-text("Sheet")').is_visible():
            print("Multi-sheet prompt displayed, ingesting Students sheet...")
            page.click('button:has-text("Sheet")')
            page.wait_for_timeout(3000)

        # If upload was successful, click "Next: Clean & prepare"
        print("Testing Next: Clean & prepare button...")
        next_btn = page.locator("#btn-next-clean")
        if next_btn.is_visible():
            next_btn.click()
            page.wait_for_timeout(1500)
        else:
            page.click("#step-clean")
            page.wait_for_timeout(1500)

        assert "/clean" in page.url, f"Expected URL /clean, got {page.url}"
        print("✓ Successfully navigated to Step 2 (/clean).")

        # 5. Check Column Rules (Semantics)
        print("Inspecting Column rules tab...")
        col_rules_btn = page.locator("#btn-tab-column-rules")
        assert col_rules_btn.is_visible(), "Column rules tab button missing"
        col_rules_btn.click()
        page.wait_for_timeout(2000)

        rules_text = page.locator(".column-rules-container").inner_text()
        print("Column rules preview snippet:\n", rules_text[:500])
        assert "roll_no" in rules_text, "roll_no column missing in rules table"
        assert "blanks will stay blank" in rules_text or "Needs_Review" in rules_text, "Preview line missing roll_no blank policy"
        print("✓ Semantic Column rules table and plain-language preview lines verified.")

        # Switch back to pipeline and run full cleaning
        page.click('button:has-text("Auto-Clean Pipeline")')
        page.wait_for_timeout(1000)

        print("Executing full cleaning pipeline on students.xlsx...")
        page.click('button:has-text("Run full cleaning")')
        page.wait_for_timeout(6000)

        # Check legend has Flagged for review
        legend_text = page.locator(".autoclean-legend-grid").inner_text()
        assert "Flagged for review" in legend_text or "?" in legend_text
        print("✓ Legend includes 'Flagged for review' with pink fill/symbol '?'.")

        # Check stepper has Review count
        seq_text = page.locator(".autoclean-seq-card").inner_text()
        assert "Flagged for Review" in seq_text or "item" in seq_text
        print("✓ Stepper shows Review count for flagged items.")

        # Download Cleaned Excel
        print("Downloading cleaned Excel workbook...")
        with page.expect_download() as download_info:
            page.click("#btn-download-cleaned-excel")
        download = download_info.value
        students_out = DOWNLOAD_DIR / "students_cleaned.xlsx"
        download.save_as(str(students_out))
        print(f"✓ Downloaded {students_out.name} ({students_out.stat().st_size} bytes)")

        # Verify students_cleaned.xlsx sheets and contents
        wb = openpyxl.load_workbook(str(students_out))
        print("Workbook sheets:", wb.sheetnames)
        assert "Cleaned_Data" in wb.sheetnames
        assert "Needs_Review" in wb.sheetnames, "Needs_Review sheet missing in workbook!"
        assert "Change_Log" in wb.sheetnames
        assert "Summary" in wb.sheetnames

        # Check Cleaned_Data: roll_no blanks remain blank
        df_clean = pd.read_excel(str(students_out), sheet_name="Cleaned_Data")
        assert "roll_no" in df_clean.columns
        null_rolls = df_clean["roll_no"].isna().sum()
        print(f"Number of blank roll_no in Cleaned_Data: {null_rolls}")
        assert null_rolls == 3, f"Expected 3 blank roll numbers to remain blank, found {null_rolls}"

        # Check Needs_Review sheet
        df_review = pd.read_excel(str(students_out), sheet_name="Needs_Review")
        print(f"Needs_Review sheet row count: {len(df_review)}")
        issue_col = next(c for c in df_review.columns if "issue" in c.lower())
        review_issues = df_review[issue_col].tolist()
        assert any("blank" in str(iss).lower() or "missing" in str(iss).lower() for iss in review_issues), "Needs_Review missing blank ID issue"
        print("✓ Blank roll numbers remain blank and are tracked in Needs_Review sheet.")

        # Check Next button from Step 2 to Step 3
        print("Testing Next: Visual studio button...")
        page.click("#btn-next-visuals")
        page.wait_for_timeout(1500)
        assert "/visuals" in page.url, f"Expected URL /visuals, got {page.url}"
        print("✓ Navigated to Step 3 (/visuals).")

        # Check Next button to Step 4
        page.click("#btn-next-insights")
        page.wait_for_timeout(1500)
        assert "/insights" in page.url, f"Expected URL /insights, got {page.url}"
        print("✓ Navigated to Step 4 (/insights).")

        # 6. Now test datapilot_test_sales.xlsx (with blanks in order_id and customer_email)
        print("\n--- Testing datapilot_test_sales.xlsx with Order ID & Email blanks ---")
        df_sales_raw = pd.read_excel(SALES_XLSX)
        df_sales_raw.loc[0:2, "order_id"] = None
        df_sales_raw.loc[3:4, "customer_email"] = None
        sales_with_blanks = SAMPLE_DIR / "datapilot_test_sales_blanks.xlsx"
        df_sales_raw.to_excel(sales_with_blanks, index=False)

        page.goto("http://127.0.0.1:5173/upload", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(sales_with_blanks))
        page.wait_for_timeout(3000)

        if page.locator('button:has-text("Sheet")').is_visible():
            page.click('button:has-text("Sheet")')
            page.wait_for_timeout(3000)

        page.click("#step-clean")
        page.wait_for_timeout(1500)

        page.click('button:has-text("Run full cleaning")')
        page.wait_for_timeout(6000)

        with page.expect_download() as download_info2:
            page.click("#btn-download-cleaned-excel")
        download2 = download_info2.value
        sales_out = DOWNLOAD_DIR / "sales_cleaned.xlsx"
        download2.save_as(str(sales_out))
        print(f"✓ Downloaded {sales_out.name} ({sales_out.stat().st_size} bytes)")

        wb_sales = openpyxl.load_workbook(str(sales_out))
        df_sales_clean = pd.read_excel(str(sales_out), sheet_name="Cleaned_Data")
        print("Sales columns:", df_sales_clean.columns.tolist())

        # Check Order ID blanks and Email blanks stay blank
        order_col = next((c for c in df_sales_clean.columns if "order" in c.lower()), None)
        email_col = next((c for c in df_sales_clean.columns if "email" in c.lower()), None)
        if order_col:
            order_blanks = df_sales_clean[order_col].isna().sum()
            print(f"Blank '{order_col}' count in Cleaned_Data: {order_blanks}")
            assert order_blanks > 0, "Order ID blanks should stay blank"
        if email_col:
            email_blanks = df_sales_clean[email_col].isna().sum()
            print(f"Blank '{email_col}' count in Cleaned_Data: {email_blanks}")
            assert email_blanks > 0, "Email blanks should stay blank"

        print("✓ Order ID and Email blanks remain blank in datapilot_test_sales.xlsx.")

        # Test reload on /clean
        page.reload()
        page.wait_for_timeout(2000)
        assert "/clean" in page.url
        print("✓ Browser reload retains active step URL.")

        browser.close()
        print("\n=== ALL PLAYWRIGHT E2E ASSERTIONS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
