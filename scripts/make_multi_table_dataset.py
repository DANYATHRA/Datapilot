"""Generate deterministic multi-table test dataset for DataPilot.

Creates in sample_data/multi_table/:
1. orders.csv
2. customers.xlsx (with 'customers' and 'regions' sheets)
3. products.csv
4. README.md (documenting grain, relationships, planted cases, and expected counts)
"""

from pathlib import Path
import pandas as pd
import openpyxl

OUT_DIR = Path(__file__).resolve().parents[1] / "sample_data" / "multi_table"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def generate_dataset():
    # ── 1. REGIONS (Dimension) ──────────────────────────────────────────
    regions_data = [
        {"region_id": "REG-NA", "region_name": "North America", "country": "United States", "manager": "Alice Morgan"},
        {"region_id": "REG-EU", "region_name": "Europe", "country": "Germany", "manager": "Bernard Weber"},
        {"region_id": "REG-APAC", "region_name": "Asia Pacific", "country": "Singapore", "manager": "Chloe Tan"},
        {"region_id": "REG-LATAM", "region_name": "Latin America", "country": "Brazil", "manager": "Diego Santos"},
    ]
    df_regions = pd.DataFrame(regions_data)

    # ── 2. CUSTOMERS (Dimension with planted cases) ─────────────────────
    # Planted cases:
    # - Duplicate PK: CUST-002 appears twice
    # - Orphan FK: CUST-008 has region_id 'REG-999' (not in regions)
    # - Null FK: CUST-005 has region_id None
    # - Missing value: CUST-004 has null email
    # - Invalid email: CUST-007 has 'invalid-email-format'
    customers_data = [
        {"customer_id": "CUST-001", "customer_name": "Acme Technologies", "region_id": "REG-NA", "segment": "Enterprise", "email": "contact@acme.example.com", "created_at": "2023-01-15"},
        {"customer_id": "CUST-002", "customer_name": "Global Solutions Ltd", "region_id": "REG-EU", "segment": "Enterprise", "email": "info@globalsolutions.example.com", "created_at": "2023-02-10"},
        {"customer_id": "CUST-002", "customer_name": "Global Solutions Duplicate", "region_id": "REG-EU", "segment": "Enterprise", "email": "duplicate@globalsolutions.example.com", "created_at": "2023-02-10"},  # DUPLICATE PK
        {"customer_id": "CUST-003", "customer_name": "Starlight Analytics", "region_id": "REG-APAC", "segment": "Mid-Market", "email": "team@starlight.example.com", "created_at": "2023-03-05"},
        {"customer_id": "CUST-004", "customer_name": "Apex Logistics", "region_id": "REG-NA", "segment": "Mid-Market", "email": None, "created_at": "2023-04-12"},  # NULL EMAIL
        {"customer_id": "CUST-005", "customer_name": "Beacon Health", "region_id": None, "segment": "Small Business", "email": "hello@beacon.example.com", "created_at": "2023-05-20"},  # NULL REGION FK
        {"customer_id": "CUST-006", "customer_name": "Nova Financial", "region_id": "REG-EU", "segment": "Enterprise", "email": "security@novafin.example.com", "created_at": "2023-06-18"},
        {"customer_id": "CUST-007", "customer_name": "Horizon Retail", "region_id": "REG-LATAM", "segment": "Small Business", "email": "invalid-email-format", "created_at": "2023-07-22"},  # INVALID EMAIL
        {"customer_id": "CUST-008", "customer_name": "Pioneer Dynamics", "region_id": "REG-999", "segment": "Enterprise", "email": "ops@pioneer.example.com", "created_at": "2023-08-30"},  # ORPHAN REGION FK
        {"customer_id": "CUST-009", "customer_name": "Vanguard Education", "region_id": "REG-NA", "segment": "Mid-Market", "email": "admin@vanguard.example.com", "created_at": "2023-09-14"},
        {"customer_id": "CUST-010", "customer_name": "Zenith Cloud", "region_id": "REG-APAC", "segment": "Small Business", "email": "cloud@zenith.example.com", "created_at": "2023-10-01"},
    ]
    df_customers = pd.DataFrame(customers_data)

    # Write customers.xlsx with two sheets: 'customers' and 'regions'
    cust_xlsx_path = OUT_DIR / "customers.xlsx"
    with pd.ExcelWriter(cust_xlsx_path, engine="openpyxl") as writer:
        df_customers.to_excel(writer, sheet_name="customers", index=False)
        df_regions.to_excel(writer, sheet_name="regions", index=False)
    print(f"Created {cust_xlsx_path} with sheets 'customers' and 'regions'")

    # ── 3. PRODUCTS (Dimension with planted cases) ──────────────────────
    # Planted cases:
    # - Inconsistent category labels: 'Software', 'software', '  Software  '
    # - Numeric outlier: PROD-107 has unit_price 15000.00
    # - Invalid value: PROD-106 has unit_cost -20.00 (negative cost)
    products_data = [
        {"product_id": "PROD-101", "product_name": "Analytics Pro Suite", "category": "Software", "unit_cost": 45.00, "unit_price": 120.00},
        {"product_id": "PROD-102", "product_name": "Cloud Data Connector", "category": "software", "unit_cost": 25.00, "unit_price": 75.00},  # INCONSISTENT CATEGORY (lowercase)
        {"product_id": "PROD-103", "product_name": "Enterprise Server Pod", "category": "Hardware", "unit_cost": 350.00, "unit_price": 850.00},
        {"product_id": "PROD-104", "product_name": "Edge Gateway Device", "category": "Hardware", "unit_cost": 180.00, "unit_price": 420.00},
        {"product_id": "PROD-105", "product_name": "BI Integration Pack", "category": "Services", "unit_cost": 120.00, "unit_price": 300.00},
        {"product_id": "PROD-106", "product_name": "Audit Consulting Hours", "category": "Services", "unit_cost": -20.00, "unit_price": 250.00},  # NEGATIVE COST
        {"product_id": "PROD-107", "product_name": "Custom AI Model Engine", "category": "  Software  ", "unit_cost": 3200.00, "unit_price": 15000.00},  # LEADING/TRAILING SPACES & PRICE OUTLIER
        {"product_id": "PROD-108", "product_name": "Predictive Pipeline Add-on", "category": "Software", "unit_cost": 80.00, "unit_price": 210.00},
    ]
    df_products = pd.DataFrame(products_data)
    prod_csv_path = OUT_DIR / "products.csv"
    df_products.to_csv(prod_csv_path, index=False)
    print(f"Created {prod_csv_path}")

    # ── 4. ORDERS (Fact table with grain order_id x product_id) ─────────
    # Planted cases:
    # - Duplicate order line: ORD-5001 line 1 appears twice identically
    # - Orphan customer FK: ORD-5016 references CUST-999
    # - Orphan product FK: ORD-5017 references PROD-999
    # - Null customer FK: ORD-5018 has customer_id = None
    # - Invalid date: ORD-5019 has date '2035-12-31' (future date)
    # - Invalid numeric: ORD-5020 has quantity = -3
    # - Missing revenue (derivable via quantity * unit_price): ORD-5015 revenue = None
    orders_data = [
        {"order_id": "ORD-5001", "customer_id": "CUST-001", "product_id": "PROD-101", "order_date": "2024-01-15", "quantity": 5, "unit_price": 120.00, "revenue": 600.00, "status": "completed"},
        {"order_id": "ORD-5001", "customer_id": "CUST-001", "product_id": "PROD-101", "order_date": "2024-01-15", "quantity": 5, "unit_price": 120.00, "revenue": 600.00, "status": "completed"},  # DUPLICATE ORDER LINE
        {"order_id": "ORD-5002", "customer_id": "CUST-002", "product_id": "PROD-103", "order_date": "2024-01-18", "quantity": 2, "unit_price": 850.00, "revenue": 1700.00, "status": "completed"},
        {"order_id": "ORD-5003", "customer_id": "CUST-003", "product_id": "PROD-102", "order_date": "2024-01-20", "quantity": 10, "unit_price": 75.00, "revenue": 750.00, "status": "completed"},
        {"order_id": "ORD-5004", "customer_id": "CUST-004", "product_id": "PROD-104", "order_date": "2024-01-25", "quantity": 4, "unit_price": 420.00, "revenue": 1680.00, "status": "completed"},
        {"order_id": "ORD-5005", "customer_id": "CUST-005", "product_id": "PROD-105", "order_date": "2024-02-02", "quantity": 1, "unit_price": 300.00, "revenue": 300.00, "status": "completed"},
        {"order_id": "ORD-5006", "customer_id": "CUST-001", "product_id": "PROD-107", "order_date": "2024-02-05", "quantity": 1, "unit_price": 15000.00, "revenue": 15000.00, "status": "completed"},
        {"order_id": "ORD-5007", "customer_id": "CUST-006", "product_id": "PROD-101", "order_date": "2024-02-12", "quantity": 8, "unit_price": 120.00, "revenue": 960.00, "status": "completed"},
        {"order_id": "ORD-5008", "customer_id": "CUST-007", "product_id": "PROD-106", "order_date": "2024-02-16", "quantity": 2, "unit_price": 250.00, "revenue": 500.00, "status": "completed"},
        {"order_id": "ORD-5009", "customer_id": "CUST-008", "product_id": "PROD-103", "order_date": "2024-02-22", "quantity": 3, "unit_price": 850.00, "revenue": 2550.00, "status": "completed"},
        {"order_id": "ORD-5010", "customer_id": "CUST-009", "product_id": "PROD-108", "order_date": "2024-03-01", "quantity": 6, "unit_price": 210.00, "revenue": 1260.00, "status": "completed"},
        {"order_id": "ORD-5011", "customer_id": "CUST-010", "product_id": "PROD-102", "order_date": "2024-03-05", "quantity": 12, "unit_price": 75.00, "revenue": 900.00, "status": "completed"},
        {"order_id": "ORD-5012", "customer_id": "CUST-002", "product_id": "PROD-105", "order_date": "2024-03-10", "quantity": 2, "unit_price": 300.00, "revenue": 600.00, "status": "completed"},
        {"order_id": "ORD-5013", "customer_id": "CUST-003", "product_id": "PROD-104", "order_date": "2024-03-18", "quantity": 5, "unit_price": 420.00, "revenue": 2100.00, "status": "completed"},
        {"order_id": "ORD-5014", "customer_id": "CUST-005", "product_id": "PROD-101", "order_date": "2024-03-24", "quantity": 4, "unit_price": 120.00, "revenue": 480.00, "status": "completed"},
        {"order_id": "ORD-5015", "customer_id": "CUST-006", "product_id": "PROD-108", "order_date": "2024-03-29", "quantity": 5, "unit_price": 210.00, "revenue": None, "status": "completed"},  # MISSING REVENUE
        {"order_id": "ORD-5016", "customer_id": "CUST-999", "product_id": "PROD-101", "order_date": "2024-04-02", "quantity": 2, "unit_price": 120.00, "revenue": 240.00, "status": "pending"},  # ORPHAN CUSTOMER FK
        {"order_id": "ORD-5017", "customer_id": "CUST-001", "product_id": "PROD-999", "order_date": "2024-04-05", "quantity": 3, "unit_price": 100.00, "revenue": 300.00, "status": "pending"},  # ORPHAN PRODUCT FK
        {"order_id": "ORD-5018", "customer_id": None, "product_id": "PROD-102", "order_date": "2024-04-08", "quantity": 1, "unit_price": 75.00, "revenue": 75.00, "status": "pending"},  # NULL CUSTOMER FK
        {"order_id": "ORD-5019", "customer_id": "CUST-004", "product_id": "PROD-104", "order_date": "2035-12-31", "quantity": 2, "unit_price": 420.00, "revenue": 840.00, "status": "pending"},  # FUTURE INVALID DATE
        {"order_id": "ORD-5020", "customer_id": "CUST-007", "product_id": "PROD-105", "order_date": "2024-04-12", "quantity": -3, "unit_price": 300.00, "revenue": -900.00, "status": "returned"},  # NEGATIVE QUANTITY
    ]
    df_orders = pd.DataFrame(orders_data)
    orders_csv_path = OUT_DIR / "orders.csv"
    df_orders.to_csv(orders_csv_path, index=False)
    print(f"Created {orders_csv_path}")

    # ── 5. DOCUMENTATION (README.md) ──────────────────────────────────
    readme_path = OUT_DIR / "README.md"
    readme_content = """# DataPilot Multi-Table Benchmark Test Dataset

## 1. Schema & Grain Overview
This multi-table dataset represents a standard commercial B2B sales schema with star/snowflake relationships:

- **Fact Table:** `orders.csv`
  - **Grain:** One record per order item line (`order_id` + `product_id`).
  - **Foreign Keys:** `customer_id` -> `customers.customer_id`, `product_id` -> `products.product_id`.
  - **Total Raw Rows:** 21 rows (20 unique order events, 1 exact duplicate line).

- **Dimension 1:** `customers.xlsx` (Sheet: `customers`)
  - **Grain:** One record per customer (`customer_id`).
  - **Foreign Key:** `region_id` -> `regions.region_id`.
  - **Total Raw Rows:** 11 rows (10 unique intended customers, 1 duplicate key `CUST-002`).

- **Dimension 2:** `customers.xlsx` (Sheet: `regions`)
  - **Grain:** One record per geographical sales region (`region_id`).
  - **Primary Key:** `region_id` (4 rows: NA, EU, APAC, LATAM).

- **Dimension 3:** `products.csv`
  - **Grain:** One record per product SKU (`product_id`).
  - **Primary Key:** `product_id` (8 rows).

---

## 2. Deliberately Planted Anomalies & Expected Results

### A. Missing & Invalid Values
- `orders.csv`:
  - `ORD-5015`: `revenue` is `NULL`. Expected derived calculation: `quantity (5) * unit_price (210.00) = 1050.00`.
  - `ORD-5019`: `order_date` is `2035-12-31` (future date, fails `date_not_future` rule).
  - `ORD-5020`: `quantity` is `-3` (negative value, fails `range(min=0)` rule).
- `customers.xlsx` (`customers` sheet):
  - `CUST-004`: `email` is `NULL`.
  - `CUST-007`: `email` is `invalid-email-format` (fails `regex` RFC email validation).
- `products.csv`:
  - `PROD-106`: `unit_cost` is `-20.00` (fails non-negative quality rule).

### B. Duplicate Keys & Rows
- `customers.xlsx`: `CUST-002` has 2 rows (Duplicate PK on the dimension).
- `orders.csv`: `ORD-5001` (product `PROD-101`) appears twice identically (1 duplicate row to remove).

### C. Orphan References (Referential Integrity Failures)
- `orders.csv` -> `customers.xlsx`:
  - `ORD-5016` has `customer_id = 'CUST-999'` (Orphan FK count: 1).
  - `ORD-5018` has `customer_id = NULL` (Null FK count: 1).
- `orders.csv` -> `products.csv`:
  - `ORD-5017` has `product_id = 'PROD-999'` (Orphan FK count: 1).
- `customers.xlsx` -> `regions`:
  - `CUST-008` has `region_id = 'REG-999'` (Orphan FK count: 1).
  - `CUST-005` has `region_id = NULL` (Null FK count: 1).

### D. Inconsistent Category Labels & Whitespace
- `products.csv`:
  - Category `Software` appears as:
    - `"Software"` (`PROD-101`, `PROD-108`)
    - `"software"` (`PROD-102`)
    - `"  Software  "` (`PROD-107`)
  - Expected clean result after text normalization: Single standardized category `"Software"`.

### E. Numeric Outliers
- `products.csv`: `PROD-107` has `unit_price = 15000.00` (vs median unit price of ~$275.00).
- `orders.csv`: `ORD-5006` has line revenue of `$15,000.00`.

---

## 3. Deterministic Expected Metric Calculations

### Expected Join Counts (Inner Join: orders ⋈ customers ⋈ products):
- Total raw orders: 21
- Deduplicated orders: 20
- Inner join on valid customers and products:
  - Excluded: `ORD-5016` (orphan customer), `ORD-5017` (orphan product), `ORD-5018` (null customer).
  - Inner join row count = **17 valid linked order lines** (or 18 including the raw duplicate before deduplication).

### Deterministic Baseline KPIs (on raw valid orders):
- **Raw Total Revenue:** Sum of valid orders = `$32,635.00` ($31,585.00 explicit + $1,050.00 derived).
- **Deduplicated Total Revenue:** `$32,035.00` (after removing the $600 duplicate).
- **Units Sold:** Sum of quantities across completed orders.
"""
    readme_path.write_text(readme_content, encoding="utf-8")
    print(f"Created {readme_path}")


if __name__ == "__main__":
    generate_dataset()
