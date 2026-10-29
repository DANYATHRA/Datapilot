# DataPilot — Intelligent Business Data & Analytics Platform

A focused, three-step application for turning raw business files into clean data and executive dashboards:
**UPLOAD** an Excel/CSV file → **CLEAN** in an interactive editable grid with inline issue fixing → **DASHBOARD** with Power BI / Tableau feel, cross-filtering, slicers, and key insights.

**Stack:** React 18 · Tailwind CSS · FastAPI · Pandas · DuckDB · ReportLab · Plotly

---

## 1. Three-Step Architecture

The platform follows a focused three-step flow:

```
[1 Upload] ────────► [2 Clean] ────────► [3 Dashboard]
(CSV / XLSX / XLS)   (Editable Grid +    (Power BI / Tableau Layout,
                      Multi-Pass Engine)  Slicers & Cross-Filtering)
```

- **Routes**: `/upload`, `/clean`, `/dashboard`.
- **Navigation Stepper**: 3 clear steps with logo at the top and user profile at the bottom.
- **Workflow Gates**: Step 2 unlocks immediately on file upload; Step 3 unlocks when the user clicks **Finish cleaning** (with confirmation and cleaning summary).

---

## 2. PART A: Complete Cleaning Contract & Automated Engine

### A1. Completeness Contract
- **Multi-Pass Loop (`run_multi_pass_auto_clean`)**: Runs up to 5 automated passes until a pass changes 0 cells, ensuring cascading fixes (e.g. whitespace trimming exposing duplicates, or currency symbol stripping enabling outlier bounds) are completely resolved.
- **Clean Check (`run_clean_check`)**: After the final pass, re-scans the entire dataset with all detectors. Displays a single status banner:
  > *"Clean. 0 issues can be fixed automatically. N need your decision."*
- **Human Decision Isolation**: Only items truly requiring human judgment remain flagged (blank unique IDs, ambiguous day/month dates, conflicting duplicate IDs, domain outliers chosen to keep).
- **Cleaning Summary Dialog**: Triggered upon clicking **Finish cleaning**, displaying:
  - Issues fixed automatically (total count and breakdown by rule: formatting, whitespace, types, duplicates, nulls).
  - Issues needing human decision (count and listed items with column and plain-language reason).
  - Actions: **Keep cleaning** and primary **Proceed to Dashboard**.

### A2. Full Suite of Detectors and Fixers
- **Structure**: Strips preambles and notes rows above headers; unmerges and fills merged cells; removes entirely blank rows and columns; removes repeated header rows; detects and strips audit/total/subtotal footers; repairs duplicate or blank headers; strips leading apostrophes.
- **Missing-Value Tokens**: Standardizes `N/A`, `NA`, `null`, `None`, `-`, `--`, `?`, `TBD`, `#VALUE!`, non-breaking spaces, and empty strings.
- **Text Normalization**: Strips leading/trailing whitespace, collapses internal whitespace, cleans zero-width and non-breaking characters, normalizes curly quotes, fixes mojibake artifacts, trims trailing punctuation.
- **Numbers**: Strips currency symbols (`₹, $, €, £, INR, USD`), handles European decimals (`1.234,56`), percentage strings (`12%` → `0.12`), accounting parentheses negatives (`(100)` → `-100`), trailing minus (`100-`), units inside numbers (`5 kg` → `5`), scientific notation, and strips trailing `.0` on integer values.
- **Dates**: Normalizes mixed date formats, parses Excel serial integers (`44927`), expands 2-digit years with a 50-year pivot, parses text months, automatically deduces `dayfirst` based on unambiguous evidence, flags future birth dates.
- **Categories**: Case standardization, boolean synonyms (`Y/N/1/0/yes/no`), and fuzzy typo deduplication ($\ge 0.75-0.85$ similarity threshold).
- **Identifiers & Contacts**: Strictly kept as strings; restores lost leading zeros; normalizes phone numbers to standard format (`+91 ...`); lowercases and validates email syntax; validates PAN, Pincode, and Aadhaar patterns.
- **Duplicate Rows**: Drops exact duplicates; for duplicate IDs, drops identical rows and flags conflicting records for human review.
- **Value Bounds & Impossible Values**: Detects negative prices/quantities/ages; percentages $> 100$; flags $3\times IQR$ extreme outliers.
- **Strict Semantic Policy**: Identifiers, emails, phones, names, and dates are **NEVER** mean/median/mode filled; money/quantities filled with group median; categories filled with mode or `"Unknown"`.

---

## 3. PART B: Power BI / Tableau Inspired Dashboard

### B1. Report Layout
- **Report Header**: Dataset name, record counts, `"Data as of <timestamp>"`, **Download report** (Executive PDF), and **Download Excel**.
- **Report Page Tabs**:
  - `Overview`: KPI row, top 4 most impactful charts in a 12-column grid, and consolidated Key Insights card.
  - `Trends`: Time-series visuals (Line, Area, Combo bar+line) with date grain drill-down controls.
  - `Breakdown`: Column, Horizontal Bar, Donut, Treemap, and Heatmap cross-tabulations.
  - `Distributions`: Histograms, Box plots (quartiles & outliers), and Scatter plots.
  - `Ratings`: Likert stacked bars and satisfaction score distributions (visible when rating scale columns exist).
- **Slicer Bar**:
  - Date range slider / start-end pickers.
  - Up to 3 searchable multi-select category dropdowns with item counts (e.g. `Electronics (142)`).
  - Single-click **Clear all slicers** button.

### B2. Visual Card Features & Interactivity
- **Hover Toolbar per Visual**:
  - 🔍 **Focus Mode**: Expands the visual into a full-screen interactive modal.
  - 🏷️ **Filters Popover**: Displays all active slicers and cross-filters applied to that visual.
  - 📊 **Show as Table**: Flips the visual into an aggregated data table featuring column headers, totals row, and inline conditional data bars sized by percentage of maximum.
  - ⬇️ **Export Data**: One-click download of the visual's aggregated data as a CSV file.
  - ⚙️ **More**: Change chart type (Column, Bar, Line, Area, Donut, Treemap) or remove visual.
- **Cross-Filtering**:
  - Clicking any data point (bar, pie slice, scatter point, or table row) filters all other visuals to that slice.
  - Selected element remains solid; unselected elements dim to opacity 0.25.
  - Active cross-filter pill appears with a 1-click dismiss button.
  - KPIs and Key Insights recompute dynamically for the cross-filtered selection.
- **Date Drill-Down**:
  - Visual cards with date measures feature drill-up / drill-down buttons (`Year` → `Quarter` → `Month` → `Day`).

### B3. Standards for Names, Axes & Legends
- **Humanized Column Names**: `order_date` → `Order Date`, `unit_price` → `Unit Price`, preserving uppercase acronyms (`ID`, `GST`, `SKU`, `PAN`).
- **Standard Measure Names**: Explicit aggregation labels (`Total Revenue`, `Average Unit Price`, `Order Count`, `Distinct Customers`).
- **Visual Titles**: Clean `<Measure> by <Dimension>` or `<Measure> over Time` titles with zero subtitles.
- **Titled Axes & Units**: Clear dimension/measure titles with units (`Revenue (₹)`, `Date (Month)`); readable tick marks; value axis always starts at zero (`rangemode: "tozero"`).
- **Auto-Switch to Horizontal Bars**: Automatically switches vertical columns to horizontal bars when category labels exceed 6 to avoid label truncation.
- **Stable 6-Color Palette**: Consistent color mapping across visuals (first 6 distinct categories mapped to primary palette, remaining mapped to neutral slate `#94A3B8`).
- **Data Labels**: Rendered directly on bars ($\le 12$) and pie slices.
- **Consolidated Key Insights**: 5–8 plain-language sentences with exact numbers reacting dynamically to slicers and cross-filtering; clicking an insight smoothly scrolls to and highlights the target chart.

---

## 4. Dual-Tab Excel Workbook Export

Both Clean and Dashboard pages feature the Excel download with strict tab ordering:
1. `Raw_Data` tab (original raw upload untouched).
2. `Processed_Data` tab (fully cleaned dataset).
3. Optional `Change_Log` tab (audit trail of every automated and manual edit).

---

## 5. Automated Verification & Test Coverage

- **Complete Cleaner & Detectors Test Suite**: `backend/tests/test_complete_cleaning.py` verifies all structural, missing token, number, date, contact, duplicate, and semantic rules on `torture_test.xlsx`.
- **BI Dashboard Unit Tests**: `backend/tests/test_bi_dashboard.py` verifies name humanization, measure aggregations, stable colors, slicer counts, and cross-filter execution.
- **Three-Step & Grid Unit Tests**: `backend/tests/test_three_step_dashboard.py` and `backend/tests/test_interactive_grid.py`.
- **Full Backend Suite**: 22 of 22 pytest tests passing.
- **Playwright E2E Verification**: `scripts/test_part_a_and_b_e2e.py` exercises the complete upload → multi-pass auto-clean → clean check banner → cleaning summary modal → Power BI / Tableau dashboard with slicers, cross-filtering, table view, focus mode, PDF report, and dual-tab Excel downloads across **1920x1080** and **1440x900** viewports.
