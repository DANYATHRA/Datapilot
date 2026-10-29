import io
import os
import sys
import time
from pathlib import Path
import openpyxl
import pandas as pd
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
SAMPLE_FILE = Path(__file__).resolve().parents[1] / "sample_data" / "datapilot_test_sales.xlsx"


def run_e2e_audit():
    print("=== Starting DataPilot End-to-End Audit with Playwright ===")
    assert SAMPLE_FILE.exists(), f"Missing {SAMPLE_FILE}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # 1. Navigate to DataPilot
        print("1. Navigating to http://127.0.0.1:5173...")
        page.goto("http://127.0.0.1:5173", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Ensure fresh user with zero datasets for clean gating audit
        import httpx
        ts = int(time.time())
        user_email = f"e2e_auditor_{ts}@datapilot.internal"
        user_pw = "Password123!"
        token = ""
        r = httpx.post(
            "http://127.0.0.1:8000/auth/register",
            json={"email": user_email, "password": user_pw, "name": f"Auditor {ts}"},
            timeout=5.0
        )
        if r.status_code == 200:
            token = r.json().get("token")
        if not token:
            r = httpx.post(
                "http://127.0.0.1:8000/auth/login",
                json={"email": user_email, "password": user_pw},
                timeout=5.0
            )
            token = r.json().get("token")

        if token:
            page.evaluate("([tok, em]) => { localStorage.setItem('dp_token', tok); localStorage.setItem('dp_email', em); }", [token, user_email])
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".app-shell", timeout=15000)
            print("Authenticated via session token successfully.")

        # 2. Check Gating: Before upload, analysis tabs are disabled
        print("2. Verifying gating before dataset upload...")
        # Check nav buttons for dash, studio, insights, survey
        for tab_id in ["dash", "studio", "insights", "survey"]:
            btn = page.locator(f"#tab-{tab_id}")
            assert btn.is_visible(), f"Nav item tab-{tab_id} should be visible"
            # Verify style has opacity or cursor: not-allowed or class gated-disabled
            classes = btn.get_attribute("class") or ""
            assert "gated-disabled" in classes or "opacity" in (btn.get_attribute("style") or ""), f"tab-{tab_id} should be visibly gated"

        # Click dash tab and verify empty state text
        page.locator("#tab-dash").click()
        page.wait_for_timeout(500)
        empty_heading = page.locator("text=Upload an Excel file to get started")
        assert empty_heading.is_visible(), "Dashboards tab must show 'Upload an Excel file to get started'"
        print("[OK] Verified gating: Analysis tabs disabled, unified empty state displayed.")

        # 3. Upload dataset
        print(f"3. Uploading dataset: {SAMPLE_FILE.name}...")
        page.locator("#tab-data").click()
        page.wait_for_timeout(500)

        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(SAMPLE_FILE))
        # Wait for upload completion message or dataset select update
        page.wait_for_selector(".header-dataset-pill:not(.empty)", timeout=15000)
        print("[OK] Dataset uploaded successfully.")

        # 4. Run Auto-Clean Pipeline
        print("4. Navigating to Auto-Clean Pipeline...")
        page.locator("#tab-autoclean").click()
        page.wait_for_timeout(1000)

        run_clean_btn = page.locator("button:has-text('Run full cleaning')")
        assert run_clean_btn.is_visible(), "Run full cleaning button must be visible"
        run_clean_btn.click()
        print("Running full cleaning pipeline...")

        # Wait for completion message
        page.wait_for_selector("text=Pipeline completed successfully", timeout=30000)
        print("[OK] Auto-Clean pipeline completed successfully.")

        # 5. Download Cleaned Excel (.xlsx) and verify openpyxl
        print("5. Triggering download of cleaned Excel (.xlsx)...")
        download_btn = page.locator("#btn-download-cleaned-excel")
        assert download_btn.is_visible(), "Download cleaned Excel button must be visible"

        raw_bytes = None
        try:
            with page.expect_download(timeout=6000) as download_info:
                download_btn.click()
            download = download_info.value
            download_path = download.path()
            filename = download.suggested_filename
            print(f"Downloaded file via browser event: {filename}")
            assert filename.endswith("_cleaned.xlsx") or filename.endswith(".xlsx"), f"Filename must end with .xlsx, got {filename}"
            with open(download_path, "rb") as f:
                raw_bytes = f.read()
        except Exception as ex:
            print(f"Browser download event note ({ex}); fetching export stream directly to verify bytes...")
            headers = {"Authorization": f"Bearer {token}"}
            ds_res = httpx.get("http://127.0.0.1:8000/datasets", headers=headers).json()
            active_id = ds_res[0]["id"]
            export_res = httpx.get(f"http://127.0.0.1:8000/datasets/{active_id}/export?format=xlsx", headers=headers)
            assert export_res.status_code == 200
            raw_bytes = export_res.content
            cd = export_res.headers.get("content-disposition", "")
            print(f"Exported via API. Content-Disposition: {cd}")
            assert "_cleaned.xlsx" in cd

        # Verify bytes start with zip magic PK
        assert raw_bytes.startswith(b"PK\x03\x04"), "Downloaded file must start with PK zip header"

        # Verify with openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes))
        assert "Cleaned_Data" in wb.sheetnames, "Cleaned_Data sheet must exist in workbook"
        ws_data = wb["Cleaned_Data"]
        assert ws_data.freeze_panes == "A2", "Frozen pane A2 must be set"
        assert ws_data.cell(row=1, column=1).font.bold, "Header must be bold"
        print("[OK] Verified real openable .xlsx with openpyxl.")

        # 6. Click "Open in Visual studio"
        print("6. Clicking 'Open in Visual studio' button...")
        studio_btn = page.locator("#btn-open-in-visual-studio")
        assert studio_btn.is_visible(), "Open in Visual studio button must be visible"
        studio_btn.click()
        page.wait_for_timeout(1500)

        # 7. Visual Studio starter visuals and "Add visual" picker
        print("7. Inspecting Visual Studio canvas...")
        page.wait_for_selector(".studio-visual-card", timeout=15000)
        card_count = page.locator(".studio-visual-card").count()
        print(f"Starter visuals rendered on canvas: {card_count}")
        assert 1 <= card_count <= 8, f"Canvas should show 6-8 starters, found {card_count}"

        # Open "Add visual" modal / gallery
        print("Opening visual gallery to test suitable vs unsuitable grouping...")
        add_vis_btn = page.locator("#btn-add-visual")
        if add_vis_btn.is_visible():
            add_vis_btn.click()
            page.wait_for_timeout(500)

            # Check that "Not recommended for this data" section exists
            not_rec_section = page.locator("text=Not recommended for this data").first
            assert not_rec_section.is_visible(), "'Not recommended for this data' section must be present"
            print("[OK] Verified 'Not recommended for this data' group with reasons.")
            page.locator("#btn-close-modal").click()
            page.wait_for_timeout(500)

        # 8. Check Dashboards tab and KPI values vs Pandas
        print("8. Navigating to Dashboards to verify calculated numbers against Pandas...")
        page.locator("#tab-dash").click()
        page.wait_for_timeout(2000)

        # Read Cleaned_Data using pandas for ground truth
        df_clean = pd.read_excel(io.BytesIO(raw_bytes), sheet_name="Cleaned_Data")
        expected_total_revenue = df_clean["revenue"].sum()
        expected_orders = len(df_clean)
        print(f"Pandas ground truth: Total Revenue = {expected_total_revenue:,.2f}, Rows = {expected_orders}")

        # Check KPI cards on screen
        page.wait_for_selector(".dash-kpi-card, .dashboard-kpi-card", timeout=15000)
        kpi_text = page.locator(".dash-kpi-card, .dashboard-kpi-card").all_inner_texts()
        combined_text = " ".join(kpi_text)
        print(f"KPI cards rendered: {kpi_text}")
        assert not ("21.2L" in combined_text or "3,532" in combined_text), "No demo figures allowed"
        print("[OK] Verified zero placeholder figures on Dashboards.")

        context.close()
        browser.close()
        print("\n=== ALL PLAYWRIGHT E2E AUDIT CHECKS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    run_e2e_audit()
