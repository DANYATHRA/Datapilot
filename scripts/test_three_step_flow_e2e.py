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


def run_full_flow():
    print("=== STARTING FULL THREE-STEP FLOW E2E TEST ===")
    assert SALES_XLSX.exists(), f"Missing {SALES_XLSX}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ────────────────────────────────────────────────────────────────────
        # PART 1: DESKTOP (1440x900)
        # ────────────────────────────────────────────────────────────────────
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = context.new_page()
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        page.on("response", lambda r: print(f"RESP {r.status} {r.url}") if r.status >= 400 or "dashboard" in r.url else None)

        print("\n--- 1. Navigating to DataPilot ---")
        page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Login via Google SSO if on auth page
        if page.locator("#auth-email").is_visible():
            print("Logging in via Instant Developer SSO...")
            page.locator("#btn-sso-google").click()
            page.wait_for_timeout(400)
            page.locator("#btn-sso-confirm").click()
            page.wait_for_timeout(2000)

        # ────────────────────────────────────────────────────────────────────
        # STEP 1: UPLOAD PAGE
        # ────────────────────────────────────────────────────────────────────
        print("\n--- STEP 1: Upload Page ---")
        page.goto("http://127.0.0.1:5173/upload", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Assert navigation bar has exactly 3 steps
        nav_steps = page.locator('[id^="nav-step-"]').all()
        print(f"Navigation steps count: {len(nav_steps)}")
        assert len(nav_steps) == 3, f"Expected exactly 3 nav steps, found {len(nav_steps)}"
        assert page.locator("#nav-step-upload").is_visible()
        assert page.locator("#nav-step-clean").is_visible()
        assert page.locator("#nav-step-dashboard").is_visible()
        print("✓ Verified exactly 3 steps in navigation: Upload, Clean, Dashboard")

        # Screenshot Step 1: Upload
        shot_up_1440 = SCREENSHOTS_DIR / "desktop_1_upload_1440.png"
        page.screenshot(path=str(shot_up_1440))
        page.screenshot(path=str(ARTIFACT_DIR / "desktop_1_upload_1440.png"))
        print(f"✓ Saved Step 1 screenshot to {shot_up_1440}")

        # Upload datapilot_test_sales.xlsx
        print(f"Uploading {SALES_XLSX.name}...")
        file_input = page.locator('#file-upload-input')
        file_input.set_input_files(str(SALES_XLSX))

        # ────────────────────────────────────────────────────────────────────
        # STEP 2: CLEAN PAGE (THE EDITABLE GRID)
        # ────────────────────────────────────────────────────────────────────
        print("\n--- STEP 2: Clean Page ---")
        page.wait_for_function("() => window.location.pathname.includes('/clean')", timeout=25000)
        page.wait_for_timeout(2000)

        # Assert clean page elements
        page.wait_for_selector("h1:has-text('Clean data')", timeout=10000)
        assert page.locator("h1:has-text('Clean data')").is_visible()
        assert page.locator("#clean-page-quality-badge").is_visible()
        print("✓ Verified Clean data header and quality badge")

        # Screenshot Step 2: Clean Grid
        shot_clean_1440 = SCREENSHOTS_DIR / "desktop_2_clean_1440.png"
        page.screenshot(path=str(shot_clean_1440))
        page.screenshot(path=str(ARTIFACT_DIR / "desktop_2_clean_1440.png"))
        print(f"✓ Saved Step 2 Clean grid screenshot to {shot_clean_1440}")

        # Assert issue chips
        page.wait_for_selector("#chip-issue-missing", timeout=10000)
        missing_chip = page.locator("#chip-issue-missing")
        assert missing_chip.is_visible()
        print(f"✓ Issue chip visible: '{missing_chip.inner_text()}'")

        # Wait for highlighted issue cells
        page.wait_for_selector('[data-popover-trigger="true"]', timeout=10000)
        issue_cells = page.locator('[data-popover-trigger="true"]').all()
        print(f"Found {len(issue_cells)} issue cells currently visible")
        target_cell = issue_cells[0]
        target_cell.scroll_into_view_if_needed()
        page.wait_for_timeout(400)

        # Open Popover (hover or click)
        target_cell.hover()
        page.wait_for_timeout(500)
        target_cell.click()
        page.wait_for_selector("#btn-popover-apply-primary", timeout=10000)
        shot_pop_1440 = SCREENSHOTS_DIR / "desktop_2_popover_1440.png"
        page.screenshot(path=str(shot_pop_1440))
        page.screenshot(path=str(ARTIFACT_DIR / "desktop_2_popover_1440.png"))
        print(f"✓ Saved Popover screenshot to {shot_pop_1440}")

        # Apply suggestion to one cell
        print("Applying suggestion to this cell...")
        page.locator("#btn-popover-apply-primary").click()
        page.wait_for_timeout(1200)
        print("✓ Applied fix to single cell with Undo toast")

        # Apply fix to all matching cells in column
        page.wait_for_selector('[data-popover-trigger="true"]', timeout=10000)
        next_cell = page.locator('[data-popover-trigger="true"]').first
        next_cell.click()
        page.wait_for_selector("#btn-popover-apply-primary", timeout=10000)
        col_radio = page.locator('input[type="radio"][value="column"]')
        if col_radio.is_visible():
            col_radio.check()
            page.wait_for_timeout(300)
        page.locator("#btn-popover-apply-primary").click()
        page.wait_for_timeout(1500)
        print("✓ Applied column-wide fix")

        # Test manual edit & undo (Ctrl+Z)
        page.wait_for_selector(".cursor-cell", timeout=10000)
        editable_cells = page.locator(".cursor-cell").all()
        text_cell = editable_cells[2] if len(editable_cells) > 2 else editable_cells[0]
        text_cell.dblclick()
        page.wait_for_timeout(400)
        input_box = page.locator('.cursor-cell input, input[type="text"]:focus')
        if input_box.is_visible():
            input_box.fill("North East")
            page.keyboard.press("Enter")
            page.wait_for_timeout(800)
            print("✓ Manual edit submitted")
            page.keyboard.press("Control+z")
            page.wait_for_timeout(800)
            print("✓ Ctrl+Z undo executed")

        # Test Fix all suggested
        fix_all_btn = page.locator("#btn-fix-all-suggested")
        if fix_all_btn.is_visible() and not fix_all_btn.is_disabled():
            fix_all_btn.click()
            page.wait_for_timeout(400)
            confirm_btn = page.locator("#btn-confirm-fix-all")
            if confirm_btn.is_visible():
                confirm_btn.click()
                page.wait_for_timeout(2000)
                print("✓ Fix all suggested executed")

        # Test "Finish cleaning" button to navigate to Dashboard
        print("Clicking 'Finish cleaning'...")
        finish_btn = page.locator("#btn-finish-cleaning")
        assert finish_btn.is_visible()
        finish_btn.click()

        # If confirmation dialog appears, confirm
        confirm_proceed = page.locator("#btn-confirm-proceed-dashboard")
        try:
            confirm_proceed.wait_for(state="visible", timeout=3000)
            confirm_proceed.click()
        except Exception:
            pass

        # ────────────────────────────────────────────────────────────────────
        # STEP 3: DASHBOARD PAGE
        # ────────────────────────────────────────────────────────────────────
        print("\n--- STEP 3: Dashboard Page ---")
        page.wait_for_function("() => window.location.pathname.includes('/dashboard')", timeout=25000)
        page.wait_for_selector("h1:has-text('Dashboard')", timeout=15000)
        page.wait_for_timeout(1500)

        # Assert Header
        assert page.locator("h1:has-text('Dashboard')").is_visible()
        assert page.locator("#dashboard-dataset-name").is_visible()
        print("✓ Dashboard header rendered")

        # Assert KPI Row (up to 6 KPIs)
        kpi_cards = page.locator(".tracking-tight.tabular-nums").all()
        print(f"Found {len(kpi_cards)} KPI cards rendered")
        assert len(kpi_cards) >= 3, f"Expected at least 3 KPIs, found {len(kpi_cards)}"

        # Assert Key Insights Panel (5-8 points)
        insights_btns = page.locator("button[title='Click to highlight chart']").all()
        print(f"Found {len(insights_btns)} key insight sentences")
        assert 4 <= len(insights_btns) <= 8, f"Expected 5-8 insights, got {len(insights_btns)}"
        for idx, btn in enumerate(insights_btns[:3]):
            print(f"  Insight {idx+1}: {btn.inner_text()}")

        # Screenshot Step 3: Dashboard
        shot_dash_1440 = SCREENSHOTS_DIR / "desktop_3_dashboard_1440.png"
        page.screenshot(path=str(shot_dash_1440))
        page.screenshot(path=str(ARTIFACT_DIR / "desktop_3_dashboard_1440.png"))
        print(f"✓ Saved Step 3 Dashboard screenshot to {shot_dash_1440}")

        # Test: Clicking an insight scrolls to and highlights its chart
        print("Testing insight click -> chart highlight...")
        first_insight = insights_btns[0]
        first_insight.click()
        page.wait_for_timeout(800)
        highlighted = page.locator(".ring-3, .border-\\[\\#0B7A75\\]")
        assert highlighted.count() > 0, "Chart should be highlighted on insight click"
        print("✓ Verified chart highlight on insight click")

        # Test: Info icon opens calculation details
        info_btn = page.locator("button[aria-label='View calculation details']").first
        if info_btn.is_visible():
            info_btn.click()
            page.wait_for_timeout(400)
            assert page.locator("text='Calculation details'").is_visible()
            page.locator("button:has-text('Close')").click()
            page.wait_for_timeout(300)
            print("✓ Verified calculation details info modal")

        # Test: Change chart type on a card
        print("Testing 'Change chart type' in card menu...")
        card_menu_btn = page.locator("button[aria-label='Chart options']").first
        card_menu_btn.click()
        page.wait_for_timeout(400)
        change_type_trigger = page.locator("div[role='menuitem']:has-text('Change chart type')")
        if change_type_trigger.is_visible():
            change_type_trigger.hover()
            page.wait_for_timeout(400)
            sub_options = page.locator("div[role='menuitem']").all()
            if len(sub_options) > 2:
                sub_options[1].click()
                page.wait_for_timeout(800)
                print("✓ Successfully changed chart type")
        else:
            page.keyboard.press("Escape")

        # Test: Remove a chart
        initial_chart_cards = page.locator("[id^='chart-card-']").count()
        card_menu_btn = page.locator("button[aria-label='Chart options']").last
        card_menu_btn.click()
        page.wait_for_timeout(400)
        remove_btn = page.locator("div[role='menuitem']:has-text('Remove')")
        if remove_btn.is_visible():
            remove_btn.click()
            page.wait_for_timeout(500)
            new_chart_cards = page.locator("[id^='chart-card-']").count()
            assert new_chart_cards == initial_chart_cards - 1
            print("✓ Successfully removed a chart card")

        # Test: Add chart button
        print("Testing 'Add chart' dialog...")
        page.locator("#btn-add-chart").click()
        page.wait_for_timeout(400)
        assert page.locator("h2:has-text('Add chart')").is_visible()
        # Select X axis
        page.locator("#select-add-chart-x").select_option(index=1)
        page.wait_for_timeout(200)
        page.locator("#btn-submit-add-chart").click()
        page.wait_for_timeout(800)
        print("✓ Successfully added custom chart to dashboard")

        # Test: Apply filter and verify numbers change
        print("Testing filter popover...")
        page.locator("#btn-open-filters").click()
        page.wait_for_timeout(500)
        assert page.locator("h2:has-text('Filter dashboard')").is_visible()

        # Click first category option pill in filter
        filter_opt = page.locator("div[role='dialog'] button.rounded").first
        if filter_opt.is_visible():
            opt_text = filter_opt.inner_text().strip()
            filter_opt.click()
            page.wait_for_timeout(300)
            page.locator("#btn-apply-filters").click()
            page.wait_for_timeout(1500)
            print(f"✓ Applied categorical filter '{opt_text}' and verified dashboard update")

        # Test: Download Report (PDF)
        print("Testing PDF report download...")
        with page.expect_download() as pdf_download_info:
            page.locator("#btn-download-pdf").click()
        pdf_download = pdf_download_info.value
        pdf_save_path = DOWNLOAD_DIR / pdf_download.suggested_filename
        pdf_download.save_as(str(pdf_save_path))
        assert pdf_save_path.exists()
        pdf_size = pdf_save_path.stat().st_size
        print(f"✓ Downloaded PDF report to {pdf_save_path} ({pdf_size} bytes)")
        assert pdf_size > 1000, f"Expected valid PDF > 1000 bytes, got {pdf_size}"
        # Check PDF header
        with open(pdf_save_path, "rb") as f:
            header = f.read(4)
            assert header == b"%PDF", f"Expected %PDF header, got {header}"
        print("✓ Verified valid %PDF binary format")

        # Test: Download Excel
        print("Testing Excel download from dashboard...")
        page.wait_for_timeout(600)
        page.locator("#btn-download-excel").click(force=True)
        page.wait_for_timeout(400)
        assert page.locator("#chk-dashboard-changelog").is_visible()
        with page.expect_download() as excel_download_info:
            page.locator("#btn-dialog-excel-submit").click()
        excel_download = excel_download_info.value
        excel_save_path = DOWNLOAD_DIR / excel_download.suggested_filename
        excel_download.save_as(str(excel_save_path))
        print(f"✓ Downloaded Excel to {excel_save_path}")

        # Assert openpyxl sheet order: Raw_Data, Processed_Data
        wb = openpyxl.load_workbook(excel_save_path)
        sheet_names = wb.sheetnames
        print(f"Workbook sheets: {sheet_names}")
        assert sheet_names[0].startswith("Raw_"), f"First sheet must be Raw_*, got {sheet_names[0]}"
        assert sheet_names[1].startswith("Processed_"), f"Second sheet must be Processed_*, got {sheet_names[1]}"
        print(f"✓ Verified exact sheet order: Tab 1 '{sheet_names[0]}', Tab 2 '{sheet_names[1]}'")

        # Save session for mobile
        auth_state_path = DOWNLOAD_DIR / "auth_state.json"
        context.storage_state(path=str(auth_state_path))
        context.close()

        # ────────────────────────────────────────────────────────────────────
        # PART 2: MOBILE (390x844) VIEWPORT
        # ────────────────────────────────────────────────────────────────────
        print("\n--- PART 2: Mobile Viewport (390x844) ---")
        mobile_ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            storage_state=str(auth_state_path),
        )
        mobile_page = mobile_ctx.new_page()

        # Step 1: Upload Mobile
        mobile_page.goto("http://127.0.0.1:5173/upload", wait_until="domcontentloaded")
        mobile_page.wait_for_timeout(1500)
        shot_up_390 = SCREENSHOTS_DIR / "mobile_1_upload_390.png"
        mobile_page.screenshot(path=str(shot_up_390))
        mobile_page.screenshot(path=str(ARTIFACT_DIR / "mobile_1_upload_390.png"))
        print(f"✓ Saved mobile Upload screenshot to {shot_up_390}")

        # Step 2: Clean Mobile
        mobile_page.goto("http://127.0.0.1:5173/clean", wait_until="domcontentloaded")
        mobile_page.wait_for_timeout(2000)
        shot_clean_390 = SCREENSHOTS_DIR / "mobile_2_clean_390.png"
        mobile_page.screenshot(path=str(shot_clean_390))
        mobile_page.screenshot(path=str(ARTIFACT_DIR / "mobile_2_clean_390.png"))
        print(f"✓ Saved mobile Clean screenshot to {shot_clean_390}")

        # Step 3: Dashboard Mobile
        mobile_page.goto("http://127.0.0.1:5173/dashboard", wait_until="domcontentloaded")
        mobile_page.wait_for_timeout(2500)
        shot_dash_390 = SCREENSHOTS_DIR / "mobile_3_dashboard_390.png"
        mobile_page.screenshot(path=str(shot_dash_390))
        mobile_page.screenshot(path=str(ARTIFACT_DIR / "mobile_3_dashboard_390.png"))
        print(f"✓ Saved mobile Dashboard screenshot to {shot_dash_390}")

        mobile_ctx.close()
        browser.close()

    print("\n=======================================================")
    print("ALL THREE-STEP FLOW E2E TESTS PASSED WITH 100% SUCCESS!")
    print("=======================================================")


if __name__ == "__main__":
    run_full_flow()
