"""Generates messy demo datasets: sample_data/sales.csv and sample_data/survey.csv"""
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)
out = Path(__file__).resolve().parent.parent / "sample_data"
out.mkdir(exist_ok=True)

# --- sales (deliberately dirty) ---
n = 600
dates = pd.date_range("2025-01-01", periods=n, freq="D")[:n]
region = rng.choice(["North", "South", "East", "West"], n, p=[.45, .2, .2, .15])
units = rng.integers(1, 20, n)
price = rng.normal(250, 30, n).round(2)
trend = np.linspace(1, 1.5, n)
shift = np.where(np.arange(n) > 400, 1.35, 1.0)
revenue = (units * price * trend * shift).round(2)
df = pd.DataFrame({
    "order_date": [d.strftime(rng.choice(["%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y"])) for d in dates],
    "region": region, "units": units, "unit_price": price,
    "revenue": ["₹{:,.2f}".format(r) for r in revenue],
    "customer_email": [f"user{i%150}@example.com" for i in range(n)],
    "phone": [f"9{rng.integers(100000000, 999999999)}" for _ in range(n)],
})
df.loc[rng.choice(n, 25, replace=False), "units"] = np.nan
df.loc[rng.choice(n, 4, replace=False), "unit_price"] = 9999.0       # outliers
df.loc[5, "region"] = " north"; df.loc[9, "region"] = "Nrth"; df.loc[12, "region"] = "SOUTH "
df = pd.concat([df, df.sample(15, random_state=1)], ignore_index=True)  # duplicates
df.to_csv(out / "sales.csv", index=False)

# --- survey ---
m = 400
gender = rng.choice(["Male", "Female"], m)
city = rng.choice(["Mumbai", "Delhi", "Bengaluru"], m)
sat = np.clip(np.round(rng.normal(3.4, 1, m) + (city == "Bengaluru") * 0.6), 1, 5).astype(int)
pd.DataFrame({
    "gender": gender, "city": city,
    "age_group": rng.choice(["18-24", "25-34", "35-44", "45+"], m),
    "q1_quality": sat, "q2_value": np.clip(sat + rng.integers(-1, 2, m), 1, 5),
    "q3_support": np.clip(sat + rng.integers(-1, 2, m), 1, 5),
    "weight": rng.uniform(0.6, 1.8, m).round(2),
}).to_csv(out / "survey.csv", index=False)
print("written to", out)
