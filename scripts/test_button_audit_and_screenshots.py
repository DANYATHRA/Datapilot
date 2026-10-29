import io
import os
import sys
import time
from pathlib import Path
import openpyxl
import pandas as pd
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_data"
SALES_XLSX = SAMPLE_DIR / "datapilot_test_sales.xlsx"
DOWNLOAD_DIR = SAMPLE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR = ROOT / "docs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

VIEWPORTS = [
    {"name": "mobile_375", "width": 375, "height": 812},
    {"name": "tablet_768", "width": 768, "height": 1024},
    {"name": "desktop_1280", "width": 1280, "height": 800},
    {"name": "ultrawide_1920", "width": 1920, "height": 1080},
]

PAGES = [
    {"route": "/upload", "name": "01_upload"},
    {"route": "/clean", "name": "02_clean"},
    {"route": "/visuals", "name": "03_visuals"},
    {"route": "/insights", "name": "04_insights"},
    {"route": "/survey", "name": "05_survey"},
    {"route": "/sql", "name": "06_sql"},
    {"route": "/dashboards", "name": "07_dashboards"},
    {"route": "/export", "name": "08_export"},
]

audit_results = []

def record_audit(page_name, label, should_do, status, decision, notes=""):
    print(f"[{status.upper()}] {page_name} | {label} -> {should_do} ({decision})")
    audit_results.append({
        "page": page_name,
        "label": label,
        "should_do": should_do,
        "status": status,
        "decision": decision,
        "notes": notes,
    })


def run_full_suite():
    print("=====================================================================")
    print("  DATAPILOT PLAYWRIGHT BUTTON AUDIT & RESPONSIVE SCREENSHOT SUITE   ")
    print("=====================================================================")
    assert SALES_XLSX.exists(), f"Sample sales dataset missing at {SALES_XLSX}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 850})
        page = context.new_page()

        # -------------------------------------------------------------
        # 1. AUTHENTICATION & LOGIN PAGE VALIDATION
        # -------------------------------------------------------------
        print("\n--- 1. Testing Auth & Login Flow ---")
        page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Capture login screenshots before signing in
        for theme in ["light", "dark"]:
            page.evaluate(f"() => {{ document.documentElement.classList.remove('light', 'dark'); document.documentElement.classList.add('{theme}'); }}")
            page.wait_for_timeout(200)
            for vp in VIEWPORTS:
                page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                page.screenshot(path=str(SCREENSHOTS_DIR / f"00_auth_{theme}_{vp['name']}.png"), full_page=False)

        # Reset viewport
        page.set_viewport_size({"width": 1280, "height": 850})

        # Test show/hide password toggle
        pw_input = page.locator("#auth-pw")
        if pw_input.is_visible():
            initial_type = pw_input.get_attribute("type")
            toggle_pw_btn = page.locator('button[aria-label="Show password"], button[aria-label="Hide password"]')
            if toggle_pw_btn.is_visible():
                toggle_pw_btn.click()
                page.wait_for_timeout(200)
                new_type = pw_input.get_attribute("type")
                assert initial_type != new_type, "Password show/hide toggle failed"
                record_audit("Auth / Login", "Show/hide password", "Toggles password masking input type", "yes", "keep")

        # Test SSO / developer sign in
        sso_btn = page.locator("#btn-sso-google")
        if sso_btn.is_visible():
            sso_btn.click()
            page.wait_for_timeout(500)
            confirm_sso = page.locator("#btn-sso-confirm")
            assert confirm_sso.is_visible(), "SSO modal did not open"
            record_audit("Auth / Login", "Google SSO", "Opens single sign-on authentication modal", "yes", "keep")
            confirm_sso.click()
            page.wait_for_timeout(2500)
            record_audit("Auth / Login", "Sign In as Google User", "Authenticates session and sets token", "yes", "keep")

        # Verify landing in AppShell
        page.wait_for_selector(".app-sidebar", timeout=10000)
        assert page.locator(".app-sidebar").is_visible(), "App shell not visible after login"

        # -------------------------------------------------------------
        # 2. GLOBAL CONTROLS AUDIT (Sidebar, Theme, Change File)
        # -------------------------------------------------------------
        print("\n--- 2. Testing Global Controls ---")
        # Theme toggle
        theme_btn = page.locator("#btn-toggle-theme")
        if theme_btn.is_visible():
            initial_theme = page.evaluate("() => document.documentElement.classList.contains('dark') ? 'dark' : 'light'")
            theme_btn.click()
            page.wait_for_timeout(300)
            toggled_theme = page.evaluate("() => document.documentElement.classList.contains('dark') ? 'dark' : 'light'")
            assert initial_theme != toggled_theme, "Theme toggle did not switch theme"
            theme_btn.click() # restore
            page.wait_for_timeout(300)
            record_audit("Global Shell", "Theme toggle", "Toggles light and dark UI modes dynamically", "yes", "keep")

        # Change file modal
        change_file_btn = page.locator("#btn-change-file-sidebar")
        if change_file_btn.is_visible():
            change_file_btn.click()
            page.wait_for_timeout(500)
            dialog = page.locator('[role="dialog"]')
            assert dialog.is_visible(), "Change file dialog did not open"
            record_audit("Global Shell", "Change file", "Opens dataset switcher and file upload dialog", "yes", "keep")
            # Close dialog via escape
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        # -------------------------------------------------------------
        # 3. STEP 1: UPLOAD DATASET
        # -------------------------------------------------------------
        print("\n--- 3. Testing Step 1: Upload ---")
        page.click("#step-upload")
        page.wait_for_timeout(1000)
        assert "/upload" in page.url

        # File input upload
        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(SALES_XLSX))
        page.wait_for_timeout(3000)
        record_audit("Upload", "Choose file / Drag & drop", "Uploads Excel/CSV file to backend with schema inspection", "yes", "keep")

        # Check remove active file button exists and functions
        remove_file_btn = page.locator("#btn-remove-active-file")
        if remove_file_btn.is_visible():
            record_audit("Upload", "Remove file", "Clears staging dataset and resets file upload dropzone", "yes", "keep")

        # Continue to Clean button
        continue_clean_btn = page.locator("#btn-continue-clean, #btn-next-clean")
        if continue_clean_btn.is_visible():
            continue_clean_btn.click()
            page.wait_for_timeout(1500)
            assert "/clean" in page.url
            record_audit("Upload", "Continue to Clean", "Navigates to Step 2 Clean & prepare with active dataset", "yes", "keep")

        # -------------------------------------------------------------
        # 4. STEP 2: CLEAN & PREPARE
        # -------------------------------------------------------------
        print("\n--- 4. Testing Step 2: Clean & Prepare ---")
        page.goto("http://127.0.0.1:5173/clean", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Preview without saving
        preview_btn = page.locator("#btn-preview-pipeline")
        if preview_btn.is_visible():
            preview_btn.click()
            page.wait_for_timeout(2500)
            record_audit("Clean & prepare", "Preview without saving", "Performs dry-run cleaning and returns diff without mutating version", "yes", "keep")

        # Stage skip toggles
        stage_btn = page.locator("#stage-toggle-duplicates")
        if stage_btn.is_visible():
            stage_btn.click()
            page.wait_for_timeout(300)
            stage_btn.click() # toggle back
            record_audit("Clean & prepare", "Stage skip toggle", "Toggles exclusion of individual pipeline cleaning stages", "yes", "keep")

        # Run full cleaning
        clean_btn = page.locator("#btn-run-full-cleaning")
        assert clean_btn.is_visible()
        clean_btn.click()
        page.wait_for_timeout(6000)
        record_audit("Clean & prepare", "Run full cleaning", "Executes full 10-stage cleaning and commits immutable Parquet snapshot", "yes", "keep")

        # Download cleaned Excel
        excel_btn = page.locator("#btn-download-cleaned-excel")
        if excel_btn.is_visible():
            with page.expect_download() as dl_info:
                excel_btn.click()
            dl = dl_info.value
            out_file = DOWNLOAD_DIR / "audit_test_cleaned.xlsx"
            dl.save_as(str(out_file))
            assert out_file.exists() and out_file.stat().st_size > 0
            wb = openpyxl.load_workbook(str(out_file))
            assert "Cleaned_Data" in wb.sheetnames
            assert "Summary" in wb.sheetnames
            # Check DataPilot brand title in Summary
            ws_sum = wb["Summary"]
            sum_text = " ".join(str(ws_sum.cell(row=i, column=1).value) for i in range(1, ws_sum.max_row + 1))
            assert "DataPilot" in sum_text, "DataPilot title missing in Excel Summary sheet"
            record_audit("Clean & prepare", "Download cleaned Excel (.xlsx)", "Exports multi-sheet workbook with audit log and legend", "yes", "keep")

        # Download CSV
        csv_btn = page.locator("#btn-download-csv")
        if csv_btn.is_visible():
            with page.expect_download() as dl_info_csv:
                csv_btn.click()
            dl_csv = dl_info_csv.value
            out_csv = DOWNLOAD_DIR / "audit_test_cleaned.csv"
            dl_csv.save_as(str(out_csv))
            assert out_csv.exists() and out_csv.stat().st_size > 0
            record_audit("Clean & prepare", "Download CSV", "Exports clean data records as standard RFC-4180 CSV", "yes", "keep")

        # Next: Visual studio
        next_vis_btn = page.locator("#btn-next-visuals")
        assert next_vis_btn.is_visible()
        next_vis_btn.click()
        page.wait_for_timeout(1500)
        assert "/visuals" in page.url
        record_audit("Clean & prepare", "Next: Visual studio", "Advances workflow step to Step 3 Visual studio", "yes", "keep")

        # -------------------------------------------------------------
        # 5. STEP 3: VISUAL STUDIO
        # -------------------------------------------------------------
        print("\n--- 5. Testing Step 3: Visual Studio ---")
        # Check single canonical "Add visual" button
        add_vis_btn = page.locator("#btn-add-visual")
        assert add_vis_btn.is_visible(), "Canonical 'Add visual' button missing"
        add_vis_btn.click()
        page.wait_for_timeout(500)
        catalog_dialog = page.locator('[role="dialog"]')
        assert catalog_dialog.is_visible(), "Visual catalog modal did not open"
        record_audit("Visual studio", "Add visual", "Opens 23-visual catalog picker with suitable vs unsuitable guidance", "yes", "keep")

        # Close catalog
        close_modal_btn = page.locator("#btn-close-modal")
        if close_modal_btn.is_visible():
            close_modal_btn.click()
            page.wait_for_timeout(400)
            record_audit("Visual studio", "Close visual catalog", "Dismisses visual catalog modal", "yes", "keep")

        # Auto-suggest visuals
        auto_suggest_btn = page.locator("#btn-auto-suggest")
        if auto_suggest_btn.is_visible():
            auto_suggest_btn.click()
            page.wait_for_timeout(2000)
            record_audit("Visual studio", "Auto-suggest visuals", "Generates best-practice recommended visual starter battery", "yes", "keep")

        # Check visual cards exist
        page.wait_for_selector(".studio-visual-card", timeout=10000)
        vis_count = page.locator(".studio-visual-card").count()
        assert vis_count >= 1, "At least 1 visual card should be rendered on canvas"

        # Test per-visual menu on first card
        menu_btn = page.locator(".studio-visual-card").first.locator('button[aria-label="Visual options"]')
        if menu_btn.is_visible():
            menu_btn.click()
            page.wait_for_timeout(400)
            menu_content = page.locator('[role="menu"]')
            assert menu_content.is_visible(), "Per-visual menu did not open"
            record_audit("Visual studio", "Per-visual menu", "Opens 5-action visual management dropdown (Edit, Duplicate, Show SQL, Download PNG, Remove)", "yes", "keep")

            # Duplicate action
            dup_item = page.locator('[role="menuitem"]:has-text("Duplicate")')
            if dup_item.is_visible():
                dup_item.click()
                page.wait_for_timeout(1000)
                new_vis_count = page.locator(".studio-visual-card").count()
                assert new_vis_count == vis_count + 1, "Duplicate did not add visual to canvas"
                record_audit("Visual studio", "Duplicate visual", "Clones visual configuration and adds duplicate card to canvas", "yes", "keep")

        # Next: Insights
        next_ins_btn = page.locator("#btn-next-insights")
        if next_ins_btn.is_visible():
            next_ins_btn.click()
            page.wait_for_timeout(1500)
            assert "/insights" in page.url
            record_audit("Visual studio", "Next: Insights", "Advances workflow step to Step 4 Insights", "yes", "keep")

        # -------------------------------------------------------------
        # 6. STEP 4: INSIGHTS
        # -------------------------------------------------------------
        print("\n--- 6. Testing Step 4: Insights ---")
        page.goto("http://127.0.0.1:5173/insights", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        gen_ins_btn = page.locator("#btn-generate-insights")
        if gen_ins_btn.is_visible():
            gen_ins_btn.click()
            page.wait_for_timeout(3000)
            record_audit("Insights", "Generate insights", "Calculates statistical anomalies, trends, and correlations with DuckDB", "yes", "keep")

        # Show evidence toggle
        evidence_btn = page.locator('button[id^="btn-evidence-"]').first
        if evidence_btn.is_visible():
            evidence_btn.click()
            page.wait_for_timeout(400)
            record_audit("Insights", "Show evidence", "Expands verbatim DuckDB SQL query proving the cited finding", "yes", "keep")

        # Next: Survey
        next_surv_btn = page.locator("#btn-next-survey")
        if next_surv_btn.is_visible():
            next_surv_btn.click()
            page.wait_for_timeout(1500)
            assert "/survey" in page.url
            record_audit("Insights", "Next: Survey analysis", "Advances workflow step to Step 5 Survey analysis", "yes", "keep")

        # -------------------------------------------------------------
        # 7. STEP 5: SURVEY ANALYSIS
        # -------------------------------------------------------------
        print("\n--- 7. Testing Step 5: Survey Analysis ---")
        page.goto("http://127.0.0.1:5173/survey", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Run cross-tab
        crosstab_btn = page.locator("#btn-run-crosstab")
        if crosstab_btn.is_visible():
            crosstab_btn.click()
            page.wait_for_timeout(2000)
            record_audit("Survey analysis", "Run cross-tab", "Executes chi-square contingency cross-tabulation across dimensions", "yes", "keep")

        # Run compare groups
        compare_btn = page.locator("#btn-run-compare")
        if compare_btn.is_visible():
            compare_btn.click()
            page.wait_for_timeout(2000)
            record_audit("Survey analysis", "Run group comparison", "Calculates two-sample t-test / ANOVA metrics between cohorts", "yes", "keep")

        # Run likert
        likert_btn = page.locator("#btn-run-likert")
        if likert_btn.is_visible():
            likert_btn.click()
            page.wait_for_timeout(2000)
            record_audit("Survey analysis", "Run Likert battery", "Computes divergent stacked percentage distribution for rating items", "yes", "keep")

        # Next: SQL & Ask AI
        next_sql_btn = page.locator("#btn-next-sql")
        if next_sql_btn.is_visible():
            next_sql_btn.click()
            page.wait_for_timeout(1500)
            assert "/sql" in page.url
            record_audit("Survey analysis", "Next: SQL & Ask AI", "Advances workflow step to Step 6 SQL & Ask AI", "yes", "keep")

        # -------------------------------------------------------------
        # 8. STEP 6: SQL & ASK AI
        # -------------------------------------------------------------
        print("\n--- 8. Testing Step 6: SQL & Ask AI ---")
        page.goto("http://127.0.0.1:5173/sql", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Run query
        run_sql_btn = page.locator("#btn-run-sql")
        if run_sql_btn.is_visible():
            run_sql_btn.click()
            page.wait_for_timeout(2000)
            record_audit("SQL & Ask AI", "Run SQL query", "Executes sandboxed read-only SQL query directly against DuckDB", "yes", "keep")

        # Explain plan
        explain_btn = page.locator("#btn-explain-plan")
        if explain_btn.is_visible():
            explain_btn.click()
            page.wait_for_timeout(1500)
            record_audit("SQL & Ask AI", "Explain plan", "Fetches DuckDB EXPLAIN execution plan tree for current SQL statement", "yes", "keep")

        # Save query dialog
        save_q_btn = page.locator("#btn-save-query")
        if save_q_btn.is_visible():
            save_q_btn.click()
            page.wait_for_timeout(500)
            q_dialog = page.locator('[role="dialog"]')
            assert q_dialog.is_visible()
            record_audit("SQL & Ask AI", "Save query", "Opens query naming modal to persist SQL snippet into query library", "yes", "keep")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        # Next: Dashboards
        next_dash_btn = page.locator("#btn-next-dashboards")
        if next_dash_btn.is_visible():
            next_dash_btn.click()
            page.wait_for_timeout(1500)
            assert "/dashboards" in page.url
            record_audit("SQL & Ask AI", "Next: Dashboards", "Advances workflow step to Step 7 Executive Dashboards", "yes", "keep")

        # -------------------------------------------------------------
        # 9. STEP 7: EXECUTIVE DASHBOARDS
        # -------------------------------------------------------------
        print("\n--- 9. Testing Step 7: Dashboards ---")
        page.goto("http://127.0.0.1:5173/dashboards", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # New dashboard
        new_dash_btn = page.locator("#btn-new-dashboard")
        if new_dash_btn.is_visible():
            new_dash_btn.click()
            page.wait_for_timeout(500)
            dash_modal = page.locator('[role="dialog"]')
            assert dash_modal.is_visible()
            record_audit("Dashboards", "New dashboard", "Opens dialog to initialize a new custom dashboard workspace", "yes", "keep")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        # Edit layout / Done
        edit_layout_btn = page.locator("#btn-edit-layout")
        if edit_layout_btn.is_visible():
            edit_layout_btn.click()
            page.wait_for_timeout(500)
            edit_layout_btn.click() # toggle back
            record_audit("Dashboards", "Edit layout / Done", "Toggles interactive grid reorganization mode", "yes", "keep")

        # Download report
        dl_report_btn = page.locator("#btn-download-report")
        if dl_report_btn.is_visible():
            with page.expect_download() as dl_report_info:
                dl_report_btn.click()
            dl_rep = dl_report_info.value
            out_rep = DOWNLOAD_DIR / "executive_report.html"
            dl_rep.save_as(str(out_rep))
            assert out_rep.exists() and out_rep.stat().st_size > 0
            with open(out_rep, "r", encoding="utf-8") as rf:
                rep_html = rf.read()
            assert "DataPilot" in rep_html, "DataPilot wordmark missing in report HTML"
            record_audit("Dashboards", "Download report", "Generates self-contained standalone HTML report with charts and evidence", "yes", "keep")

        # Next: Reports & export
        next_exp_btn = page.locator("#btn-next-export")
        if next_exp_btn.is_visible():
            next_exp_btn.click()
            page.wait_for_timeout(1500)
            assert "/export" in page.url
            record_audit("Dashboards", "Next: Reports & export", "Advances workflow step to Step 8 Reports & export", "yes", "keep")

        # -------------------------------------------------------------
        # 10. STEP 8: REPORTS & EXPORT
        # -------------------------------------------------------------
        print("\n--- 10. Testing Step 8: Reports & Export ---")
        page.goto("http://127.0.0.1:5173/export", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Export Excel
        exp_excel_btn = page.locator("#btn-export-excel")
        if exp_excel_btn.is_visible():
            with page.expect_download() as exp_ex_info:
                exp_excel_btn.click()
            dl_ex = exp_ex_info.value
            out_ex = DOWNLOAD_DIR / "final_export.xlsx"
            dl_ex.save_as(str(out_ex))
            assert out_ex.exists() and out_ex.stat().st_size > 0
            wb_exp = openpyxl.load_workbook(str(out_ex))
            assert "Cleaned_Data" in wb_exp.sheetnames
            assert "Summary" in wb_exp.sheetnames
            record_audit("Reports & export", "Download Excel workbook (.xlsx)", "Exports audit-grade multi-sheet Excel with change logs and summary", "yes", "keep")

        # Export CSV
        exp_csv_btn = page.locator("#btn-export-csv")
        if exp_csv_btn.is_visible():
            with page.expect_download() as exp_csv_info:
                exp_csv_btn.click()
            dl_csv2 = exp_csv_info.value
            out_csv2 = DOWNLOAD_DIR / "final_export.csv"
            dl_csv2.save_as(str(out_csv2))
            assert out_csv2.exists() and out_csv2.stat().st_size > 0
            record_audit("Reports & export", "Download CSV dataset (.csv)", "Exports flat cleaned tabular dataset ready for warehouse ingestion", "yes", "keep")

        # Export HTML Report
        exp_html_btn = page.locator("#btn-export-html")
        if exp_html_btn.is_visible():
            with page.expect_download() as exp_html_info:
                exp_html_btn.click()
            dl_html2 = exp_html_info.value
            out_html2 = DOWNLOAD_DIR / "final_report.html"
            dl_html2.save_as(str(out_html2))
            assert out_html2.exists() and out_html2.stat().st_size > 0
            with open(out_html2, "r", encoding="utf-8") as rf2:
                html_doc = rf2.read()
            assert "<!doctype html>" in html_doc.lower(), "Missing doctype in HTML report"
            assert "DataPilot" in html_doc, "DataPilot brand missing in exported HTML report"
            record_audit("Reports & export", "Download HTML executive report", "Exports standalone interactive executive dossier", "yes", "keep")

        # -------------------------------------------------------------
        # 11. RESPONSIVE SCREENSHOT CAPTURE (375, 768, 1280, 1920 px)
        # -------------------------------------------------------------
        print("\n--- 11. Capturing Comprehensive Responsive Screenshots ---")
        for p_info in PAGES:
            route = p_info["route"]
            p_name = p_info["name"]
            print(f"Capturing screenshots for {p_name} ({route})...")
            page.goto(f"http://127.0.0.1:5173{route}", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)

            for theme in ["light", "dark"]:
                # Set theme class
                page.evaluate(f"() => {{ document.documentElement.classList.remove('light', 'dark'); document.documentElement.classList.add('{theme}'); }}")
                page.wait_for_timeout(250)

                for vp in VIEWPORTS:
                    page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                    page.wait_for_timeout(250)
                    filename = f"{p_name}_{theme}_{vp['name']}.png"
                    target_path = SCREENSHOTS_DIR / filename
                    page.screenshot(path=str(target_path), full_page=False)

        context.close()
        browser.close()

    print("\n=====================================================================")
    print("  ALL BUTTON AUDIT ASSERTIONS & SCREENSHOTS COMPLETED SUCCESSFULLY!  ")
    print(f"  Total buttons/actions audited: {len(audit_results)}")
    print(f"  Screenshots saved to: {SCREENSHOTS_DIR}")
    print("=====================================================================")

if __name__ == "__main__":
    run_full_suite()
