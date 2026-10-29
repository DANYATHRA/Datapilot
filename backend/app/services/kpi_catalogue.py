"""Domain KPI catalogue.

KPI templates by domain: Sales, Marketing, Finance, HR, Operations/Supply chain,
Customer/Survey, Education.  Each KPI has: name, plain-English definition,
formula, required column roles, and recommended visuals.

When a dataset is loaded, detects likely domain from column semantics and shows
available KPIs.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# ── KPI catalogue ──────────────────────────────────────────────────

KPI_CATALOGUE: dict[str, list[dict]] = {
    "Sales": [
        {"name": "Total Revenue", "definition": "Sum of all revenue generated from sales",
         "formula": "SUM({revenue})", "required_roles": ["revenue"],
         "recommended_visuals": ["kpi_card", "line", "bar"]},
        {"name": "Average Order Value", "definition": "Average revenue per order",
         "formula": "SUM({revenue}) / COUNT(DISTINCT {order_id})", "required_roles": ["revenue", "order_id"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Units Sold", "definition": "Total number of units sold",
         "formula": "SUM({quantity})", "required_roles": ["quantity"],
         "recommended_visuals": ["kpi_card", "bar"]},
        {"name": "Revenue Growth %", "definition": "Percentage change in revenue vs previous period",
         "formula": "(SUM({revenue}_current) - SUM({revenue}_previous)) / SUM({revenue}_previous) * 100",
         "required_roles": ["revenue", "date"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Gross Margin %", "definition": "Revenue minus cost divided by revenue",
         "formula": "(SUM({revenue}) - SUM({cost})) / SUM({revenue}) * 100",
         "required_roles": ["revenue", "cost"],
         "recommended_visuals": ["kpi_card", "gauge"]},
        {"name": "Discount Rate", "definition": "Average discount percentage across orders",
         "formula": "AVG({discount})", "required_roles": ["discount"],
         "recommended_visuals": ["kpi_card", "histogram"]},
        {"name": "Sales by Region", "definition": "Revenue breakdown by geographical region",
         "formula": "SUM({revenue}) GROUP BY {region}", "required_roles": ["revenue", "region"],
         "recommended_visuals": ["bar", "pie", "choropleth"]},
        {"name": "Top Products", "definition": "Products ranked by revenue",
         "formula": "SUM({revenue}) GROUP BY {product} ORDER BY SUM({revenue}) DESC",
         "required_roles": ["revenue", "product"],
         "recommended_visuals": ["bar", "table"]},
    ],
    "Marketing": [
        {"name": "Conversion Rate", "definition": "Percentage of leads that became customers",
         "formula": "COUNT({converted}) / COUNT({leads}) * 100",
         "required_roles": ["converted", "leads"],
         "recommended_visuals": ["kpi_card", "funnel"]},
        {"name": "Cost per Acquisition", "definition": "Marketing spend divided by new customers",
         "formula": "SUM({marketing_spend}) / COUNT(DISTINCT {customer_id})",
         "required_roles": ["marketing_spend", "customer_id"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Click-Through Rate", "definition": "Clicks divided by impressions",
         "formula": "SUM({clicks}) / SUM({impressions}) * 100",
         "required_roles": ["clicks", "impressions"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Campaign ROI", "definition": "Return on investment for campaigns",
         "formula": "(SUM({revenue}) - SUM({marketing_spend})) / SUM({marketing_spend}) * 100",
         "required_roles": ["revenue", "marketing_spend"],
         "recommended_visuals": ["kpi_card", "bar"]},
    ],
    "Finance": [
        {"name": "Net Profit", "definition": "Total revenue minus total expenses",
         "formula": "SUM({revenue}) - SUM({expenses})",
         "required_roles": ["revenue", "expenses"],
         "recommended_visuals": ["kpi_card", "waterfall"]},
        {"name": "Profit Margin %", "definition": "Net profit as a percentage of revenue",
         "formula": "(SUM({revenue}) - SUM({expenses})) / SUM({revenue}) * 100",
         "required_roles": ["revenue", "expenses"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Expense Ratio", "definition": "Operating expenses as a percentage of revenue",
         "formula": "SUM({expenses}) / SUM({revenue}) * 100",
         "required_roles": ["expenses", "revenue"],
         "recommended_visuals": ["kpi_card", "pie"]},
        {"name": "Accounts Receivable Aging", "definition": "Average days to collect payment",
         "formula": "AVG({days_outstanding})",
         "required_roles": ["days_outstanding"],
         "recommended_visuals": ["kpi_card", "bar"]},
    ],
    "HR": [
        {"name": "Employee Count", "definition": "Total number of active employees",
         "formula": "COUNT(DISTINCT {employee_id})",
         "required_roles": ["employee_id"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Attrition Rate", "definition": "Percentage of employees who left",
         "formula": "COUNT({terminated}) / COUNT({employee_id}) * 100",
         "required_roles": ["terminated", "employee_id"],
         "recommended_visuals": ["kpi_card", "bar"]},
        {"name": "Average Salary", "definition": "Mean salary across employees",
         "formula": "AVG({salary})",
         "required_roles": ["salary"],
         "recommended_visuals": ["kpi_card", "histogram"]},
        {"name": "Gender Pay Gap", "definition": "Difference in average salary by gender",
         "formula": "AVG({salary}) GROUP BY {gender}",
         "required_roles": ["salary", "gender"],
         "recommended_visuals": ["bar", "kpi_card"]},
    ],
    "Operations": [
        {"name": "On-Time Delivery %", "definition": "Percentage of orders delivered on or before the due date",
         "formula": "COUNT({on_time}) / COUNT({order_id}) * 100",
         "required_roles": ["order_id", "delivery_date", "due_date"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Inventory Turnover", "definition": "Cost of goods sold divided by average inventory",
         "formula": "SUM({cogs}) / AVG({inventory_value})",
         "required_roles": ["cogs", "inventory_value"],
         "recommended_visuals": ["kpi_card", "bar"]},
        {"name": "Order Fulfillment Time", "definition": "Average days from order to delivery",
         "formula": "AVG({delivery_date} - {order_date})",
         "required_roles": ["order_date", "delivery_date"],
         "recommended_visuals": ["kpi_card", "histogram"]},
        {"name": "Defect Rate", "definition": "Percentage of defective items",
         "formula": "SUM({defects}) / SUM({total_produced}) * 100",
         "required_roles": ["defects", "total_produced"],
         "recommended_visuals": ["kpi_card", "line"]},
    ],
    "Customer": [
        {"name": "Customer Satisfaction (CSAT)", "definition": "Average satisfaction score",
         "formula": "AVG({satisfaction_score})",
         "required_roles": ["satisfaction_score"],
         "recommended_visuals": ["kpi_card", "gauge"]},
        {"name": "Net Promoter Score", "definition": "% Promoters minus % Detractors",
         "formula": "(COUNT({promoters}) - COUNT({detractors})) / COUNT({responses}) * 100",
         "required_roles": ["nps_score"],
         "recommended_visuals": ["kpi_card", "bar"]},
        {"name": "Customer Retention Rate", "definition": "Percentage of customers retained over a period",
         "formula": "(COUNT({end_customers}) - COUNT({new_customers})) / COUNT({start_customers}) * 100",
         "required_roles": ["customer_id", "date"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Average Response Time", "definition": "Average time to respond to customer queries",
         "formula": "AVG({response_time})",
         "required_roles": ["response_time"],
         "recommended_visuals": ["kpi_card", "histogram"]},
    ],
    "Education": [
        {"name": "Average Grade", "definition": "Mean grade across students",
         "formula": "AVG({grade})",
         "required_roles": ["grade"],
         "recommended_visuals": ["kpi_card", "histogram"]},
        {"name": "Pass Rate", "definition": "Percentage of students who passed",
         "formula": "COUNT({passed}) / COUNT({student_id}) * 100",
         "required_roles": ["student_id", "grade"],
         "recommended_visuals": ["kpi_card", "bar"]},
        {"name": "Enrollment Count", "definition": "Total number of enrolled students",
         "formula": "COUNT(DISTINCT {student_id})",
         "required_roles": ["student_id"],
         "recommended_visuals": ["kpi_card", "line"]},
        {"name": "Attendance Rate", "definition": "Average attendance percentage",
         "formula": "AVG({attendance_pct})",
         "required_roles": ["attendance_pct"],
         "recommended_visuals": ["kpi_card", "bar"]},
    ],
}

# ── Role mapping ───────────────────────────────────────────────────
# Maps semantic types and column name patterns to KPI roles

ROLE_PATTERNS: dict[str, list[str]] = {
    "revenue": ["revenue", "sales", "total_sales", "amount", "total_amount", "turnover", "income"],
    "cost": ["cost", "cogs", "cost_of_goods", "expense", "unit_cost"],
    "quantity": ["quantity", "qty", "units", "units_sold", "count", "volume"],
    "order_id": ["order_id", "order_number", "invoice_id", "transaction_id"],
    "customer_id": ["customer_id", "client_id", "account_id", "cust_id"],
    "product": ["product", "product_name", "item", "sku", "product_id"],
    "region": ["region", "territory", "area", "zone", "country", "state", "city", "location"],
    "date": ["date", "order_date", "transaction_date", "created_at", "timestamp"],
    "discount": ["discount", "discount_pct", "discount_rate", "discount_amount"],
    "employee_id": ["employee_id", "emp_id", "staff_id", "worker_id"],
    "salary": ["salary", "wage", "pay", "compensation", "base_pay"],
    "gender": ["gender", "sex"],
    "grade": ["grade", "score", "marks", "gpa"],
    "student_id": ["student_id", "roll_number", "enrollment_id"],
    "satisfaction_score": ["satisfaction", "csat", "rating", "feedback_score"],
    "nps_score": ["nps", "nps_score", "promoter_score"],
    "delivery_date": ["delivery_date", "delivered_at", "ship_date"],
    "due_date": ["due_date", "expected_date", "promised_date"],
    "order_date": ["order_date", "purchase_date", "placed_at"],
    "expenses": ["expenses", "operating_expenses", "opex", "total_expenses"],
    "marketing_spend": ["marketing_spend", "ad_spend", "campaign_cost"],
    "clicks": ["clicks", "click_count"],
    "impressions": ["impressions", "views", "view_count"],
    "leads": ["leads", "lead_count", "prospects"],
    "converted": ["converted", "conversions", "conversion_count"],
    "attendance_pct": ["attendance", "attendance_pct", "attendance_rate"],
    "response_time": ["response_time", "resolution_time", "handle_time"],
}


def detect_domain(df: pd.DataFrame, semantics: dict | None = None) -> tuple[str, dict[str, str]]:
    """Detect the likely business domain and map columns to KPI roles.

    Returns: (domain_name, {role: column_name})
    """
    col_names = [str(c).lower().replace(" ", "_") for c in df.columns]
    col_map = dict(zip(col_names, df.columns))

    # Score each role
    role_assignments: dict[str, str] = {}
    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            for cn, orig in col_map.items():
                if pattern == cn or (len(pattern) > 3 and pattern in cn):
                    role_assignments[role] = str(orig)
                    break
            if role in role_assignments:
                break

    # Use semantic types as fallback
    if semantics:
        sem_to_role = {
            "revenue": "revenue", "price": "revenue", "unit_price": "revenue",
            "quantity": "quantity", "date": "date", "datetime": "date",
            "id": "order_id", "customer_name": "customer_id",
            "rating_scale": "satisfaction_score", "percentage": "discount",
        }
        for col, info in semantics.items():
            sem_type = info.get("semantic_type", "")
            role = sem_to_role.get(sem_type)
            if role and role not in role_assignments:
                role_assignments[role] = col

    # Score domains based on how many required roles are satisfied
    domain_scores: dict[str, int] = {}
    for domain, kpis in KPI_CATALOGUE.items():
        score = 0
        for kpi in kpis:
            required = kpi["required_roles"]
            if all(r in role_assignments for r in required):
                score += 1
        domain_scores[domain] = score

    best_domain = max(domain_scores, key=lambda d: domain_scores[d])
    if domain_scores[best_domain] == 0:
        best_domain = "Sales"  # fallback

    return best_domain, role_assignments


def get_available_kpis(domain: str, role_assignments: dict[str, str]) -> list[dict]:
    """Return KPIs for a domain, marking which are available for the data."""
    kpis = KPI_CATALOGUE.get(domain, [])
    result = []
    for kpi in kpis:
        required = kpi["required_roles"]
        available = all(r in role_assignments for r in required)
        missing = [r for r in required if r not in role_assignments]
        mapped_columns = {r: role_assignments[r] for r in required if r in role_assignments}

        result.append({
            **kpi,
            "available": available,
            "missing_roles": missing,
            "mapped_columns": mapped_columns,
        })

    # Sort: available first
    result.sort(key=lambda k: (not k["available"], k["name"]))
    return result


def compute_kpi(df: pd.DataFrame, kpi: dict, role_assignments: dict[str, str]) -> dict | None:
    """Compute a KPI value from a DataFrame using role assignments.

    Returns: {name, value, formatted, formula_used}
    """
    required = kpi["required_roles"]
    if not all(r in role_assignments for r in required):
        return None

    try:
        formula = kpi["formula"]
        name = kpi["name"]

        if name == "Total Revenue":
            col = role_assignments["revenue"]
            value = float(df[col].sum())
        elif name == "Average Order Value":
            rev_col = role_assignments["revenue"]
            oid_col = role_assignments["order_id"]
            value = float(df[rev_col].sum() / max(df[oid_col].nunique(), 1))
        elif name == "Units Sold":
            col = role_assignments["quantity"]
            value = float(df[col].sum())
        elif name == "Gross Margin %":
            rev = df[role_assignments["revenue"]].sum()
            cost = df[role_assignments["cost"]].sum()
            value = float((rev - cost) / max(rev, 1) * 100)
        elif name == "Discount Rate":
            col = role_assignments["discount"]
            value = float(df[col].mean())
        elif name == "Employee Count":
            col = role_assignments["employee_id"]
            value = int(df[col].nunique())
        elif name == "Average Salary":
            col = role_assignments["salary"]
            value = float(df[col].mean())
        elif name == "Average Grade":
            col = role_assignments["grade"]
            value = float(df[col].mean())
        elif name == "Enrollment Count":
            col = role_assignments["student_id"]
            value = int(df[col].nunique())
        elif name == "Customer Satisfaction (CSAT)":
            col = role_assignments["satisfaction_score"]
            value = float(df[col].mean())
        else:
            # Generic: try to compute SUM of the first required numeric column
            for role in required:
                col = role_assignments.get(role, "")
                if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                    value = float(df[col].sum())
                    break
            else:
                return None

        # Format
        if "%" in name or "Rate" in name or "Margin" in name:
            formatted = f"{value:.1f}%"
        elif value >= 1_000_000:
            formatted = f"{value / 1_000_000:.2f}M"
        elif value >= 1_000:
            formatted = f"{value / 1_000:.1f}K"
        elif isinstance(value, float):
            formatted = f"{value:.2f}"
        else:
            formatted = str(value)

        return {"name": name, "value": value, "formatted": formatted, "formula_used": formula,
                "definition": kpi["definition"]}

    except Exception:
        return None


detect_domain_and_roles = detect_domain
