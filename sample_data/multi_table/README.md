# DataPilot Multi-Table Benchmark Test Dataset

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
