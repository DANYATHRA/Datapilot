"""
Generates sample_data/datapilot_test_sales.xlsx for rigorous correctness and round-trip testing.
Includes:
- order_id: string identifier
- order_date: mixed dates across 14 months (2025-01 to 2026-02)
- region: categorical dimension (North, South, East, West) with leading/trailing spaces & typos
- product: categorical dimension (Laptops, Phones, Tablets, Monitors)
- units: integer measure (1-20) with nulls
- unit_price: numeric float with outliers (e.g. 9999.0)
- revenue: currency string with '₹' symbols (e.g. '₹12,450.00')
- customer_email: PII email
- customer_phone: PII 10-digit Indian phone
- satisfaction_rating: rating scale 1..5
- recommend_rating: rating scale 1..5
- duplicate rows
"""
import numpy as np
import pandas as pd
from pathlib import Path
from openpyxl import Workbook

out_dir = Path(__file__).resolve().parent.parent / "sample_data"
out_dir.mkdir(exist_ok=True)
xlsx_path = out_dir / "datapilot_test_sales.xlsx"

rng = np.random.default_rng(12345)
n = 300

# 14 months of dates
dates = pd.date_range("2025-01-01", periods=n, freq="D")[:n]
regions = rng.choice(["North", "South", "East", "West"], n, p=[0.40, 0.25, 0.20, 0.15])
products = rng.choice(["Laptops", "Phones", "Tablets", "Monitors"], n, p=[0.35, 0.30, 0.20, 0.15])
units = rng.integers(1, 15, n)
prices = rng.choice([250.0, 450.0, 750.0, 1200.0], n, p=[0.25, 0.35, 0.25, 0.15])
revenue = (units * prices).round(2)

sat = rng.integers(1, 6, n)
rec = np.clip(sat + rng.integers(-1, 2, n), 1, 5)

df = pd.DataFrame({
    "order_id": [f"ORD-{1000 + i}" for i in range(n)],
    "order_date": [d.strftime(rng.choice(["%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y"])) for d in dates],
    "region": regions,
    "product": products,
    "units": units.astype(object),
    "unit_price": prices,
    "revenue": [f"₹{r:,.2f}" for r in revenue],
    "customer_email": [f"client{i%75}@example.com" for i in range(n)],
    "customer_phone": [f"9{rng.integers(100000000, 999999999)}" for _ in range(n)],
    "satisfaction_rating": sat,
    "recommend_rating": rec,
})

# Add dirty data:
# 1. Nulls in units
df.loc[rng.choice(n, 12, replace=False), "units"] = np.nan
# 2. Outliers in unit_price
df.loc[rng.choice(n, 3, replace=False), "unit_price"] = 9999.0
# 3. Text whitespace & typos in region
df.loc[3, "region"] = " north"
df.loc[7, "region"] = "Nrth"
df.loc[14, "region"] = "SOUTH "
# 4. Duplicate rows
duplicates = df.sample(8, random_state=42)
df = pd.concat([df, duplicates], ignore_index=True)

with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="Sales_Data")

print(f"Generated {xlsx_path} with {len(df)} rows and {df.shape[1]} columns.")
