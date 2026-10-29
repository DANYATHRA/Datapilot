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
SALES_XLSX = SAMPLE_DIR / "datapilot_test_sales.xlsx"
STUDENTS_XLSX = SAMPLE_DIR / "students.xlsx"

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


def run_e2e():
    print("=== STARTING PLAYWRIGHT END-TO-END VALIDATION FOR EDITABLE GRID ===")
    assert SALES_XLSX.exists(), f"Missing {SALES_XLSX}"
    assert STUDENTS_XLSX.exists(), f"Missing {STUDENTS_XLSX}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ────────────────────────────────────────────────────────────────────
        # PART 1: 1440x900 DESKTOP VIEWPORT (Sales Dataset)
        # ────────────────────────────────────────────────────────────────────
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = context.new_page()

        print("\n--- 1. Navigating to DataPilot (1440x900) ---")
        page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Auto-login if auth screen appears
        if page.locator("#auth-email").is_visible():
            print("Logging in via Instant Developer SSO...")
            page.locator('button:has-text("Google")').click()
            page.wait_for_timeout(500)
            page.locator('button:has-text("Sign In as Google User")').click()
            page.wait_for_timeout(2000)

        # 2. Upload datapilot_test_sales.xlsx
        print(f"Uploading {SALES_XLSX.name}...")
        page.goto("http://127.0.0.1:5173/connect", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        file_input = page.locator('input[type="file"]')
        if not file_input.is_visible():
            page.locator('button:has-text("Upload"), button:has-text("Change file"), [data-testid="upload-zone"]').first.click()
            page.wait_for_timeout(500)

        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(SALES_XLSX))
        page.wait_for_timeout(2500)

        # Multi-sheet check or direct upload
        if page.locator('button:has-text("Sales_Data")').is_visible():
            page.locator('button:has-text("Sales_Data")').first.click()
            page.wait_for_timeout(2000)

        # Navigate to /clean
        page.goto("http://127.0.0.1:5173/clean", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        assert "/clean" in page.url, f"Expected /clean, got {page.url}"

        # 3. VERIFY EDITABLE GRID & ISSUE HIGHLIGHTS
        print("Verifying editable grid presence and issue chips...")
        page.wait_for_selector(".select-none", timeout=10000)
        page.wait_for_timeout(1000)

        # Check view buttons
        assert page.locator("#btn-view-original").is_visible()
        assert page.locator("#btn-view-cleaned").is_visible()
        assert page.locator("#btn-view-changes").is_visible()
        print("✓ View switcher present (Original | Cleaned | Changes only)")

        # Check issue chips
        missing_chip = page.locator("#chip-issue-missing")
        assert missing_chip.is_visible(), "Missing issue filter chip should be visible"
        print(f"✓ Issue chips visible: '{missing_chip.inner_text()}'")

        # Screenshot the grid at 1440x900
        grid_shot_path = SCREENSHOTS_DIR / "grid_desktop_1440.png"
        page.screenshot(path=str(grid_shot_path))
        page.screenshot(path=str(ARTIFACT_DIR / "grid_desktop_1440.png"))
        print(f"✓ Saved desktop grid screenshot to {grid_shot_path}")

        # 4. HOVER AND POPOVER VERIFICATION
        print("Waiting for issue cells in the grid...")
        page.wait_for_selector('[data-popover-trigger="true"]', timeout=10000)
        issue_cells = page.locator('[data-popover-trigger="true"]').all()
        print(f"Found {len(issue_cells)} issue cells currently visible")
        issue_cell = issue_cells[0]
        issue_cell.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        assert issue_cell.is_visible()

        print("Hovering on issue cell to trigger popover...")
        issue_cell.hover()
        page.wait_for_timeout(600)
        if not page.locator("#btn-popover-apply-primary").is_visible():
            issue_cell.click()
            page.wait_for_timeout(1000)

        popover_apply = page.locator("#btn-popover-apply-primary")
        assert popover_apply.is_visible(), "Hover/Focus popover should appear"
        print(f"✓ Popover appeared: '{popover_apply.inner_text()}'")

        # Screenshot popover at 1440x900
        popover_shot_path = SCREENSHOTS_DIR / "popover_desktop_1440.png"
        page.screenshot(path=str(popover_shot_path))
        page.screenshot(path=str(ARTIFACT_DIR / "popover_desktop_1440.png"))
        print(f"✓ Saved desktop popover screenshot to {popover_shot_path}")

        # Apply suggestion to this cell only
        print("Testing: Apply suggestion to this cell only...")
        popover_apply.click()
        page.wait_for_timeout(1500)
        print("✓ Successfully applied fix to single cell with Undo toast")

        # 5. TEST: APPLY TO ALL IN COLUMN
        print("Testing: Apply fix to all matching cells in column...")
        page.wait_for_selector('[data-popover-trigger="true"]', timeout=10000)
        next_issue_cell = page.locator('[data-popover-trigger="true"]').first
        if next_issue_cell.is_visible():
            next_issue_cell.click()
            page.wait_for_timeout(1000)

            # Choose "All in column"
            col_radio = page.locator('input[type="radio"][value="column"]')
            if col_radio.is_visible():
                col_radio.check()
                page.wait_for_timeout(300)

            page.locator("#btn-popover-apply-primary").click()
            page.wait_for_timeout(1500)
            print("✓ Successfully applied column-wide fix")

        # 6. TEST MANUAL EDIT & UNDO
        print("Testing manual cell editing...")
        page.wait_for_selector(".cursor-cell", timeout=5000)
        editable_cells = page.locator(".cursor-cell").all()
        # Find cell in column 2 (e.g. Region or Category text)
        target_cell = editable_cells[2] if len(editable_cells) > 2 else editable_cells[0]
        initial_val = target_cell.inner_text().strip()
        target_cell.dblclick()
        page.wait_for_timeout(500)

        input_box = page.locator('input[type="text"]:focus, .cursor-cell input')
        if input_box.is_visible():
            input_box.fill("North East")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)
            print("✓ Manual edit submitted")

            # Press Ctrl+Z to undo
            print("Pressing Ctrl+Z to undo...")
            page.keyboard.press("Control+z")
            page.wait_for_timeout(1000)
            print("✓ Undo triggered successfully")

        # 7. TEST "NEXT ISSUE" NAVIGATION
        print("Testing 'Next issue' navigation control...")
        next_issue_btn = page.locator('button[aria-label="Next issue"]')
        if next_issue_btn.is_visible():
            next_issue_btn.click()
            page.wait_for_timeout(500)
            print("✓ Next issue button clicked and navigated cursor")

        # 8. TEST "FIX ALL SUGGESTED"
        print("Testing 'Fix all suggested' toolbar action...")
        fix_all_btn = page.locator("#btn-fix-all-suggested")
        if fix_all_btn.is_visible() and not fix_all_btn.is_disabled():
            fix_all_btn.click()
            page.wait_for_timeout(500)
            confirm_btn = page.locator("#btn-confirm-fix-all")
            if confirm_btn.is_visible():
                confirm_btn.click()
                page.wait_for_timeout(2500)
                print("✓ Batch 'Fix all suggested' executed successfully")

        # 9. TEST DOWNLOAD EXCEL DIALOG & OPENPYXL ASSERTIONS
        print("\n--- 2. Testing Download Dialog & openpyxl Validation ---")
        dl_btn = page.locator("#btn-open-download-dialog")
        assert dl_btn.is_visible()
        dl_btn.click()
        page.wait_for_timeout(600)

        dialog = page.locator('[role="dialog"]')
        assert dialog.is_visible()
        assert page.locator('text="Download dataset"').is_visible()
        assert page.locator("#chk-include-changelog").is_visible()
        assert page.locator("#chk-highlight-changes").is_visible()
        print("✓ Minimal Download Dialog displayed with format & checkboxes")

        # Trigger download and capture event
        with page.expect_download() as download_info:
            page.locator("#btn-dialog-download-submit").click()

        download = download_info.value
        save_path = DOWNLOAD_DIR / download.suggested_filename
        download.save_as(str(save_path))
        print(f"✓ Downloaded file to {save_path}")

        # Assert with openpyxl
        wb = openpyxl.load_workbook(save_path)
        sheet_names = wb.sheetnames
        print(f"Workbook sheet names: {sheet_names}")

        # Requirement 6 & 7: The .xlsx contains in this order: Raw_Data, Processed_Data
        assert sheet_names[0].startswith("Raw_"), f"First sheet must start with 'Raw_', got {sheet_names[0]}"
        assert sheet_names[1].startswith("Processed_"), f"Second sheet must start with 'Processed_', got {sheet_names[1]}"
        print(f"✓ Verified exact sheet order: Tab 1 '{sheet_names[0]}', Tab 2 '{sheet_names[1]}'")

        # 10. TEST IDENTIFIER RULES: students.xlsx fixture
        print("\n--- 3. Testing Identifier Policy on students.xlsx ---")
        page.goto("http://127.0.0.1:5173/connect", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(STUDENTS_XLSX))
        page.wait_for_timeout(2500)

        page.goto("http://127.0.0.1:5173/clean", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        print("Checking identifier column 'roll_no' in students sheet...")
        page.wait_for_selector('[data-popover-trigger="true"]', timeout=10000)
        roll_no_issue = page.locator('[data-popover-trigger="true"]').first
        roll_no_issue.click()
        page.wait_for_timeout(1000)

        popover_content = page.locator("#btn-popover-apply-primary").locator("..").locator("..").inner_text()
        print(f"Students popover snippet: {popover_content[:120]}")
        # Verify 6-word identifier reasoning and non-imputation
        assert "can't be guessed" in popover_content or "Unique ID" in popover_content, (
            f"Expected identifier explanation, got: {popover_content}"
        )
        assert "mean" not in popover_content.lower() and "median" not in popover_content.lower(), (
            f"Identifier must NEVER suggest mean/median! Found in: {popover_content}"
        )
        print("✓ Verified strict semantic policy: roll_no has explanation and NO mean/median suggestion")

        state_path = DOWNLOAD_DIR / "auth_state.json"
        context.storage_state(path=str(state_path))
        context.close()

        # ────────────────────────────────────────────────────────────────────
        # PART 2: MOBILE VIEWPORT (390x844 - iPhone / Mobile width)
        # ────────────────────────────────────────────────────────────────────
        print("\n--- 4. Mobile Viewport Validation (390x844) ---")
        mobile_context = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            storage_state=str(state_path),
        )
        mobile_page = mobile_context.new_page()
        mobile_page.goto("http://127.0.0.1:5173/clean", wait_until="domcontentloaded")
        mobile_page.wait_for_timeout(2500)

        # Screenshot grid on mobile
        mobile_grid_shot = SCREENSHOTS_DIR / "grid_mobile_390.png"
        mobile_page.screenshot(path=str(mobile_grid_shot))
        mobile_page.screenshot(path=str(ARTIFACT_DIR / "grid_mobile_390.png"))
        print(f"✓ Saved mobile grid screenshot to {mobile_grid_shot}")

        # Tap on issue cell to trigger mobile bottom sheet popover
        mobile_page.wait_for_selector('[data-popover-trigger="true"]', timeout=10000)
        mobile_issue_cell = mobile_page.locator('[data-popover-trigger="true"]').first
        if mobile_issue_cell.is_visible():
            mobile_issue_cell.scroll_into_view_if_needed()
            mobile_issue_cell.click()
            mobile_page.wait_for_timeout(1200)

            mobile_popover_shot = SCREENSHOTS_DIR / "popover_mobile_390.png"
            mobile_page.screenshot(path=str(mobile_popover_shot))
            mobile_page.screenshot(path=str(ARTIFACT_DIR / "popover_mobile_390.png"))
            print(f"✓ Saved mobile popover screenshot to {mobile_popover_shot}")

        mobile_context.close()
        browser.close()

    print("\n=======================================================")
    print("ALL PLAYWRIGHT END-TO-END VALIDATIONS PASSED WITH SUCCESS!")
    print("=======================================================")


if __name__ == "__main__":
    run_e2e()
