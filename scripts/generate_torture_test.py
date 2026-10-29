import openpyxl
from openpyxl.styles import Font
from pathlib import Path

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Torture_Data"

# Row 1: Title preamble
ws.cell(row=1, column=1, value="ACME Global Enterprise - Data Quality Torture Test Report")
ws.cell(row=1, column=1).font = Font(bold=True, size=14)

# Row 2: Subtitle notes
ws.cell(row=2, column=1, value="Confidential: Raw data export with complex real-world anomalies")

# Row 3: Blank preamble row

# Row 4: Column Headers
headers = [
    "order_id", "customer_name", "email", "phone", "pan_number",
    "region", "category", "status", "is_priority", "order_date",
    "dob", "units", "unit_price", "discount_pct", "total_amount", "notes"
]
for col_idx, h in enumerate(headers, 1):
    c = ws.cell(row=4, column=col_idx, value=h)
    c.font = Font(bold=True)

# Data rows (starting row 5)
data = [
    # Normal base row
    ["00101", "Alice Smith", "alice.smith@example.com", "+91 98765 43210", "ABCDE1234F", "North", "Electronics", "Active", "Yes", "2023-01-15", "1990-05-12", 5, 1200.0, "10%", 6000.0, "Standard order"],
    # Text number, European decimal, mojibake, curly quote, spaces
    ["00102", "Bob  Jones", " BOB.JONES@EXAMPLE.COM ", "09876543211", "BCDEF2345G", "South", "Furniture", "active", "true", "15/01/2023", "1985-08-20", "10 kg", "1.250,50", "15%", 12505.0, "Bob\u2019s \u201cSpecial\u201d Chairs"],
    # Parentheses negative, thousands separator with space, text date, boolean 1
    ["00103", "Charlie Brown", "charlie@brown.org", "+91-98765-43212", "CDEFG3456H", "East", "Electronics", "ACTIVE", "1", "15-Jan-2023", "1992-11-03", "15", "2 500.00", "0%", 37500.0, "Normal note"],
    # Currency symbols (₹, $), trailing minus, Excel serial date, typo in category
    ["00104", "Diana Prince", "diana@themyscira.com", "9876543213", "DEFGH4567I", "West", "Electrnics", "Pending", "Y", 44927, "1988-03-25", "2.0", "₹ 3,500", "5%", 7000.0, "Trailing punctuation,"],
    # Lost leading zero in ID (105), thousands separator comma, 2-digit year, boolean True
    ["105", "Evan Wright", "evan@wright.net", "+91 98765 43214", "EFGHI5678J", "North", "Furniture", "Active", "True", "20/02/23", "1995-12-14", 8, "4,200", "12%", 33600.0, "'Leading apostrophe text"],
    # Missing tokens: 'N/A', 'null', '-', '?', 'TBD', '#VALUE!'
    ["00106", "Fiona Gallagher", "fiona@gallagher.tv", "N/A", "FGHIJ6789K", "South", "Supplies", "null", "-", "25/03/2023", "1994-07-07", "?", "TBD", "#VALUE!", None, "Has missing tokens"],
    # Duplicate ID with identical data (should be dropped)
    ["00101", "Alice Smith", "alice.smith@example.com", "+91 98765 43210", "ABCDE1234F", "North", "Electronics", "Active", "Yes", "2023-01-15", "1990-05-12", 5, 1200.0, "10%", 6000.0, "Standard order"],
    # Conflicting duplicate ID (00107) -> Needs review
    ["00107", "George Clark", "george@clark.com", "+91 98765 43215", "GHIJK7890L", "East", "Electronics", "Active", "Yes", "2023-04-10", "1982-01-30", 4, 1500.0, "5%", 6000.0, "First record"],
    ["00107", "George DIFFERENT", "different@clark.com", "+91 98765 43215", "GHIJK7890L", "East", "Furniture", "Closed", "No", "2023-04-10", "1982-01-30", 10, 8000.0, "20%", 80000.0, "Conflicting record"],
    # Semantic missing rules: Blank ID (needs decision), blank email (needs decision), blank units (group median fill)
    ["", "Hannah Abbott", "", "+91 98765 43216", "HIJKL8901M", "North", "Electronics", "Active", "Yes", "2023-05-01", "1993-09-18", None, 1200.0, "10%", None, "Blank ID and email"],
    # Impossible values: Negative price (-500), percentage > 100 (150%), future DOB (2035-01-01)
    ["00108", "Ian Malcolm", "ian@jurassic.org", "+91 98765 43217", "IJKLM9012N", "West", "Electronics", "Active", "No", "2023-06-12", "2035-01-01", 3, -500.0, "150%", -1500.0, "Chaos theory"],
    # Invalid formats: Invalid email, invalid PAN
    ["00109", "Julia Roberts", "not-a-valid-email", "+91 98765 43218", "INVALID_PAN", "South", "Supplies", "Active", "false", "2023-07-04", "1975-10-28", 12, 150.0, "0%", 1800.0, "Invalid contacts"],
    # Outlier value (999999)
    ["00110", "Kevin Bacon", "kevin@sixdegrees.com", "+91 98765 43219", "JKLMN0123O", "North", "Electronics", "Active", "Yes", "2023-08-19", "1968-07-08", 2, 999999.0, "5%", 1999998.0, "Extreme outlier"],
    # Scientific notation: 1.5e+01, trailing minus: 100-
    ["00111", "Laura Croft", "laura@tomb.org", "+91 98765 43220", "KLMNO1234P", "West", "Electronics", "Active", "1", "2023-09-02", "1991-02-14", "1.5e+01", "100-", "10%", 1500.0, "Tomb Raider"],
]

for row_idx, r_data in enumerate(data, 5):
    for col_idx, val in enumerate(r_data, 1):
        ws.cell(row=row_idx, column=col_idx, value=val)

# Add a completely blank row in the middle
blank_row_idx = len(data) + 6

# Add a repeated header row inside data
rep_header_idx = blank_row_idx + 1
for col_idx, h in enumerate(headers, 1):
    ws.cell(row=rep_header_idx, column=col_idx, value=h)

# Add one more data row after repeated header
after_row_idx = rep_header_idx + 1
after_data = ["00112", "Mike Ross", "mike@suits.legal", "+91 98765 43221", "LMNOP2345Q", "East", "Supplies", "Active", "Yes", "2023-10-15", "1989-06-21", 6, 450.0, "5%", 2700.0, "Legal aid"]
for col_idx, val in enumerate(after_data, 1):
    ws.cell(row=after_row_idx, column=col_idx, value=val)

# Add Total / Subtotal row at the end
subtotal_row_idx = after_row_idx + 1
ws.cell(row=subtotal_row_idx, column=1, value="Subtotal")
ws.cell(row=subtotal_row_idx, column=12, value="=SUM(L5:L18)")

grand_total_idx = subtotal_row_idx + 1
ws.cell(row=grand_total_idx, column=1, value="Grand Total")
ws.cell(row=grand_total_idx, column=15, value="=SUM(O5:O18)")

# Add an entirely blank column (Column 17)
for r in range(4, grand_total_idx + 1):
    ws.cell(row=r, column=17, value=None)

# Add merged cells in a notes block
ws.merge_cells(start_row=grand_total_idx + 2, start_column=1, end_row=grand_total_idx + 2, end_column=4)
ws.cell(row=grand_total_idx + 2, column=1, value="Audit Footer: Verified by Automated Quality Gate")

out_path = Path("sample_data/torture_test.xlsx")
wb.save(out_path)
print(f"Successfully generated torture test fixture at {out_path} ({out_path.stat().st_size} bytes)")

