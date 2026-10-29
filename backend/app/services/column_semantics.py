"""
Column Semantics Detection Engine.
Infers semantic_type, confidence (0.0 - 1.0), and evidence for every column from BOTH column name and data values.
"""
from __future__ import annotations

import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

SEMANTIC_TYPES = [
    "identifier",
    "name",
    "email",
    "phone",
    "address/free_text",
    "date",
    "year",
    "age",
    "quantity",
    "money_amount",
    "percentage",
    "rating_scale",
    "score/marks",
    "category",
    "status/boolean_flag",
    "gender",
    "postal_code",
    "url",
    "other_numeric",
    "other_text",
]

# Name token patterns (case-insensitive)
NAME_PATTERNS: dict[str, list[str]] = {
    "identifier": [
        "id", "no", "number", "num", "roll", "rollno", "rollnumber", "reg", "regno",
        "registration", "code", "sku", "uuid", "ref", "reference", "empid", "orderid",
        "custid", "studentid", "emp_id", "order_id", "roll_no", "reg_no", "order_number",
        "employee_id", "student_id", "customer_id", "invoice_no", "bill_no"
    ],
    "name": [
        "name", "firstname", "lastname", "fullname", "fname", "lname", "student", "customer",
        "employee", "client", "person", "user", "author", "candidate"
    ],
    "email": ["email", "mail", "e_mail", "emailid", "email_id"],
    "phone": ["phone", "mobile", "contact", "cell", "telephone", "phone_no", "mobile_no"],
    "address/free_text": [
        "address", "addr", "street", "city", "state", "region", "country",
        "province", "location", "notes", "comment", "description", "remarks"
    ],
    "date": [
        "dob", "date", "dt", "birth", "joining", "order_date", "timestamp", "created_at",
        "updated_at", "ship_date", "delivery_date"
    ],
    "year": ["year", "yr", "acad_year", "academic_year", "session", "passout_year"],
    "age": ["age"],
    "quantity": ["qty", "quantity", "units", "count", "items", "volume", "pieces", "stock", "ordered"],
    "money_amount": [
        "price", "amount", "revenue", "cost", "total", "fee", "fees", "salary",
        "wage", "fare", "bill", "subtotal", "net", "gross", "income", "expense", "unit_price"
    ],
    "percentage": [
        "pct", "percent", "percentage", "discount", "share", "rate", "attendance",
        "attendance_pct", "ratio"
    ],
    "rating_scale": ["rating", "satisfaction", "feedback", "likert", "score_rating", "review_score", "stars"],
    "score/marks": ["score", "marks", "grade", "gpa", "cgpa", "exam", "test_score", "marks_obtained"],
    "category": [
        "category", "type", "class", "section", "dept", "department", "division",
        "group", "tier", "segment", "branch", "channel", "brand"
    ],
    "status/boolean_flag": ["status", "is_active", "active", "flag", "enabled", "verified", "passed", "present"],
    "gender": ["gender", "sex"],
    "postal_code": ["pin", "pincode", "zip", "zipcode", "postal", "postal_code"],
    "url": ["url", "link", "website", "site", "webpage", "uri"],
}

# Regex patterns for data inspection
EMAIL_RX = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
PHONE_10_RX = re.compile(r"^(\+91[\-\s]?)?[6-9]\d{9}$")
PHONE_DIGIT_RX = re.compile(r"^\+?\d{10,13}$")
PINCODE_6_RX = re.compile(r"^\d{6}$")
AADHAAR_RX = re.compile(r"^\d{4}\s?\d{4}\s?\d{4}$|^\d{12}$")
PAN_RX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
URL_RX = re.compile(r"^(https?://|www\.)[^\s/$.?#].[^\s]*$", re.IGNORECASE)
CURRENCY_SYMBOLS = re.compile(r"[₹$€£¥]")


def _split_name_tokens(col_name: str) -> list[str]:
    """Split column name into tokens on whitespace, underscore, hyphen, dot, or camelCase."""
    s = str(col_name).strip()
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    tokens = [t.lower().strip("._-#") for t in re.split(r"[\s_\-\.]+", s) if t.strip("._-#")]
    full_clean = "".join(tokens)
    return tokens + ([full_clean] if full_clean and full_clean not in tokens else [])


def _match_name_tokens(col_name: str) -> list[tuple[str, float]]:
    """Match column name against semantic dictionaries returning (semantic_type, score)."""
    tokens = _split_name_tokens(col_name)
    matches: list[tuple[str, float]] = []

    # Check for specific high-priority types first
    raw_lower = str(col_name).lower().strip()
    clean_lower = re.sub(r"[\s_\-\.]+", "", raw_lower)

    # Identifiers: roll no, roll_no, rollnumber, reg. no, reg_no, order id, employee id, id, etc.
    id_direct_hits = {"roll", "rollno", "rollnumber", "reg", "regno", "sku", "uuid", "empid", "orderid", "custid", "studentid"}
    if any(tok in id_direct_hits for tok in tokens) or clean_lower in id_direct_hits:
        return [("identifier", 1.0)]

    # Phone check before generic 'no'
    if any(tok in ("phone", "mobile", "cell", "telephone") for tok in tokens):
        return [("phone", 1.0)]

    # Postal code check before generic 'code'
    if any(tok in ("pin", "pincode", "zip", "zipcode", "postal") for tok in tokens):
        return [("postal_code", 1.0)]

    for sem_type, patterns in NAME_PATTERNS.items():
        score = 0.0
        for pat in patterns:
            pat_clean = pat.replace("_", "")
            for tok in tokens:
                if tok == pat or tok == pat_clean:
                    score = max(score, 1.0)
                elif pat in tok and len(pat) >= 3:
                    score = max(score, 0.75)
        if score > 0:
            matches.append((sem_type, score))

    # Priority adjustments:
    # If both identifier (e.g. from 'id' or 'no') and name (e.g. from 'employee') match, identifier wins for keys
    types_found = {m[0] for m in matches}
    if "identifier" in types_found and "name" in types_found:
        if any(tok in ("id", "no", "number", "code", "ref") for tok in tokens):
            matches = [m for m in matches if m[0] != "name"]

    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def profile_series_data(s: pd.Series) -> dict[str, Any]:
    """Inspect the actual data values in a series for semantic signals."""
    non_null = s.dropna()
    n_valid = len(non_null)
    if n_valid == 0:
        return {"empty": True, "n_valid": 0, "null_pct": 1.0}

    str_vals = non_null.astype(str).str.strip()
    str_vals = str_vals[str_vals != ""]
    n_str = len(str_vals)
    if n_str == 0:
        return {"empty": True, "n_valid": 0, "null_pct": 1.0}

    unique_count = non_null.nunique()
    uniqueness_ratio = unique_count / n_valid if n_valid > 0 else 0.0

    # Test numeric conversion
    clean_numeric_str = str_vals.str.replace(r"[₹$€£¥,%\s]", "", regex=True)
    numeric_series = pd.to_numeric(clean_numeric_str, errors="coerce")
    num_valid = numeric_series.dropna()
    num_ratio = len(num_valid) / n_str if n_str > 0 else 0.0

    # Currency and percent presence
    has_currency = str_vals.str.contains(CURRENCY_SYMBOLS, regex=True).mean() > 0.05
    has_percent = str_vals.str.contains("%", regex=False).mean() > 0.05

    # Date parsing test
    date_ratio = 0.0
    if not str_vals.str.fullmatch(r"-?\d+(\.\d+)?").mean() > 0.5:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed_dates = pd.to_datetime(str_vals.head(200), errors="coerce", format="mixed")
            date_ratio = float(parsed_dates.notna().mean())

    # Format regex ratios
    email_ratio = float(str_vals.map(lambda x: bool(EMAIL_RX.match(x))).mean())
    phone_ratio = float(str_vals.map(lambda x: bool(PHONE_10_RX.match(x) or (PHONE_DIGIT_RX.match(x) and len(re.sub(r'\D', '', x)) == 10))).mean())
    pincode_ratio = float(str_vals.map(lambda x: bool(PINCODE_6_RX.match(x))).mean())
    aadhaar_ratio = float(str_vals.map(lambda x: bool(AADHAAR_RX.match(x))).mean())
    pan_ratio = float(str_vals.map(lambda x: bool(PAN_RX.match(x))).mean())
    url_ratio = float(str_vals.map(lambda x: bool(URL_RX.match(x))).mean())

    # Numeric range and integer analysis
    is_all_int = False
    num_min, num_max = None, None
    is_seq = False
    if num_ratio > 0.85 and len(num_valid) > 0:
        is_all_int = bool((num_valid % 1 == 0).all())
        num_min = float(num_valid.min())
        num_max = float(num_valid.max())
        # Check integer sequence (1, 2, 3...)
        if is_all_int and uniqueness_ratio > 0.95 and len(num_valid) >= 3:
            sorted_vals = np.sort(num_valid.values)
            diffs = np.diff(sorted_vals)
            if np.all(diffs == 1):
                is_seq = True

    # Check gender tokens
    gender_tokens = {"male", "female", "m", "f", "other", "transgender", "non-binary"}
    gender_ratio = float(str_vals.str.lower().isin(gender_tokens).mean())

    # Check boolean tokens
    bool_tokens = {"yes", "no", "y", "n", "true", "false", "1", "0", "pass", "fail", "present", "absent"}
    bool_ratio = float(str_vals.str.lower().isin(bool_tokens).mean())

    return {
        "empty": False,
        "n_valid": n_valid,
        "null_pct": float(s.isna().mean()),
        "unique_count": unique_count,
        "uniqueness_ratio": uniqueness_ratio,
        "num_ratio": num_ratio,
        "is_all_int": is_all_int,
        "num_min": num_min,
        "num_max": num_max,
        "is_seq": is_seq,
        "has_currency": has_currency,
        "has_percent": has_percent,
        "date_ratio": date_ratio,
        "email_ratio": email_ratio,
        "phone_ratio": phone_ratio,
        "pincode_ratio": pincode_ratio,
        "aadhaar_ratio": aadhaar_ratio,
        "pan_ratio": pan_ratio,
        "url_ratio": url_ratio,
        "gender_ratio": gender_ratio,
        "bool_ratio": bool_ratio,
    }


def infer_column_semantic_type(col_name: str, s: pd.Series) -> dict[str, Any]:
    """
    Infer semantic type, confidence (0.0 to 1.0), and evidence for a single column.
    Name AND data agreement produces high confidence; disagreement flags 'please confirm'.
    """
    data_prof = profile_series_data(s)
    name_matches = _match_name_tokens(col_name)
    top_name_type = name_matches[0][0] if name_matches else None
    name_score = name_matches[0][1] if name_matches else 0.0

    if data_prof["empty"]:
        sem = top_name_type or "other_text"
        return {
            "semantic_type": sem,
            "confidence": 0.50 if top_name_type else 0.30,
            "evidence": f"Empty column; inferred from name '{col_name}'",
            "needs_confirmation": True,
            "name_hint": top_name_type,
            "data_signals": ["empty column"],
        }

    evidence: list[str] = []
    candidates: dict[str, float] = {}

    # 1. Regex & Pattern Checks (High Signal)
    if data_prof["email_ratio"] >= 0.7:
        candidates["email"] = candidates.get("email", 0) + 0.95
        evidence.append(f"{data_prof['email_ratio']:.0%} email pattern match")
    if data_prof["url_ratio"] >= 0.7:
        candidates["url"] = candidates.get("url", 0) + 0.95
        evidence.append(f"{data_prof['url_ratio']:.0%} URL pattern match")
    if data_prof["phone_ratio"] >= 0.6:
        candidates["phone"] = candidates.get("phone", 0) + 0.92
        evidence.append(f"{data_prof['phone_ratio']:.0%} 10-digit phone match")
    if data_prof["pincode_ratio"] >= 0.75 and top_name_type in ("postal_code", "address/free_text", None):
        candidates["postal_code"] = candidates.get("postal_code", 0) + 0.88
        evidence.append(f"{data_prof['pincode_ratio']:.0%} 6-digit postal code match")
    if data_prof["aadhaar_ratio"] >= 0.75:
        candidates["identifier"] = candidates.get("identifier", 0) + 0.90
        evidence.append(f"{data_prof['aadhaar_ratio']:.0%} 12-digit Aadhaar / ID pattern match")
    if data_prof["pan_ratio"] >= 0.75:
        candidates["identifier"] = candidates.get("identifier", 0) + 0.90
        evidence.append(f"{data_prof['pan_ratio']:.0%} PAN format match")
    if data_prof["gender_ratio"] >= 0.75:
        candidates["gender"] = candidates.get("gender", 0) + 0.90
        evidence.append(f"{data_prof['gender_ratio']:.0%} gender token match")

    # 2. Date Checks
    if data_prof["date_ratio"] >= 0.65:
        candidates["date"] = candidates.get("date", 0) + 0.88
        evidence.append(f"{data_prof['date_ratio']:.0%} parseable dates")

    # 3. Numeric & Rating / Score / Money / Quantity
    if data_prof["num_ratio"] >= 0.85:
        num_min = data_prof["num_min"]
        num_max = data_prof["num_max"]
        is_all_int = data_prof["is_all_int"]
        uniq = data_prof["unique_count"]

        # Year check: 1900 <= year <= 2100
        if is_all_int and num_min is not None and num_max is not None and 1900 <= num_min <= 2100 and 1900 <= num_max <= 2100:
            candidates["year"] = candidates.get("year", 0) + 0.90
            evidence.append(f"Integer values in year range {int(num_min)}–{int(num_max)}")

        # Rating scale: 1..k where k <= 11
        if is_all_int and num_min is not None and num_max is not None and 1 <= num_min and num_max <= 11 and 2 <= uniq <= 11:
            candidates["rating_scale"] = candidates.get("rating_scale", 0) + 0.88
            evidence.append(f"Integer rating scale (1 to {int(num_max)})")

        # Age check: 0 <= age <= 120
        if is_all_int and num_min is not None and num_max is not None and 0 <= num_min and num_max <= 120 and top_name_type == "age":
            candidates["age"] = candidates.get("age", 0) + 0.92
            evidence.append(f"Integer values in age range {int(num_min)}–{int(num_max)}")

        # Percentage check
        if data_prof["has_percent"] or (top_name_type == "percentage" and num_min is not None and num_max is not None and 0 <= num_min and num_max <= 100):
            candidates["percentage"] = candidates.get("percentage", 0) + 0.88
            evidence.append("Percentage indicators / 0–100 range")

        # Score / Marks: bounded 0-100
        if top_name_type == "score/marks" and num_min is not None and num_min >= 0:
            candidates["score/marks"] = candidates.get("score/marks", 0) + 0.88
            evidence.append("Score/exam marks range")

        # Currency / Money amount
        if data_prof["has_currency"] or (top_name_type == "money_amount" and num_min is not None and num_min >= 0):
            candidates["money_amount"] = candidates.get("money_amount", 0) + 0.90
            evidence.append("Currency formatting or monetary magnitude")

        # Quantity
        if is_all_int and num_min is not None and num_min >= 0 and top_name_type == "quantity":
            candidates["quantity"] = candidates.get("quantity", 0) + 0.90
            evidence.append("Non-negative integer unit counts")

        # Identifier sequence or integer ID (only if name matches identifier or sequential integer without monetary/quantity name)
        if top_name_type == "identifier" or (data_prof["is_seq"] and top_name_type is None):
            candidates["identifier"] = candidates.get("identifier", 0) + 0.92
            evidence.append(f"Integer sequence or key ({data_prof['uniqueness_ratio']:.0%} unique)")

    # 4. Text / Alphanumeric Identifier (>= 0.98 and not float, or name matches identifier)
    if (top_name_type == "identifier" and data_prof["uniqueness_ratio"] >= 0.80) or (
        data_prof["uniqueness_ratio"] >= 0.98 and data_prof["n_valid"] >= 3 and not (data_prof["num_ratio"] > 0.85 and top_name_type in ("money_amount", "quantity", "percentage", "score/marks", "age"))
    ):
        candidates["identifier"] = candidates.get("identifier", 0) + 0.90
        evidence.append(f"Identifier key pattern ({data_prof['uniqueness_ratio']:.0%} uniqueness)")

    # 5. Low Cardinality Category (cardinality <= 20 and not identifier, name, phone, email, date)
    if data_prof["unique_count"] <= 20 and data_prof["n_valid"] >= 3:
        if top_name_type not in ("identifier", "name", "phone", "email", "date", "rating_scale", "status/boolean_flag"):
            if data_prof["uniqueness_ratio"] < 0.70 or top_name_type == "category":
                candidates["category"] = candidates.get("category", 0) + 0.80
                evidence.append(f"Low cardinality ({data_prof['unique_count']} unique categories)")

    # 6. Person's Name
    if top_name_type == "name" and data_prof["uniqueness_ratio"] > 0.40 and data_prof["num_ratio"] < 0.30:
        candidates["name"] = candidates.get("name", 0) + 0.90
        evidence.append("Personal name textual tokens")

    # 6. Boolean / Status Flag
    if data_prof["bool_ratio"] >= 0.85 and data_prof["unique_count"] <= 4:
        candidates["status/boolean_flag"] = candidates.get("status/boolean_flag", 0) + 0.88
        evidence.append(f"Binary / status indicators ({data_prof['bool_ratio']:.0%})")

    # Blend Name Evidence
    if top_name_type:
        evidence.append(f"Column name '{col_name}' matches {top_name_type}")
        current_score = candidates.get(top_name_type, 0.0)
        candidates[top_name_type] = current_score + (0.35 if current_score > 0 else 0.55 * name_score)

    # Resolve Best Semantic Type
    if not candidates:
        if data_prof["num_ratio"] > 0.8:
            sem_type = "other_numeric"
            conf = 0.65
            evidence.append("General numeric values")
        else:
            sem_type = "other_text"
            conf = 0.60
            evidence.append("General textual data")
    else:
        sorted_cand = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
        sem_type = sorted_cand[0][0]
        raw_score = sorted_cand[0][1]

        # Calculate confidence
        name_agrees = (top_name_type == sem_type)
        if name_agrees and name_score >= 0.7:
            conf = min(0.98, max(0.88, raw_score))
        elif top_name_type is None:
            conf = min(0.85, max(0.68, raw_score * 0.85))
        else:
            # Name and data disagree -> low confidence, flag please confirm
            conf = min(0.65, max(0.45, raw_score * 0.60))
            evidence.append(f"Disagreement: Name suggests '{top_name_type}' but data suggests '{sem_type}' (please confirm)")

    needs_confirmation = conf < 0.75

    return {
        "semantic_type": sem_type,
        "confidence": round(conf, 2),
        "evidence": " • ".join(evidence),
        "needs_confirmation": needs_confirmation,
        "name_hint": top_name_type,
        "null_pct": round(data_prof["null_pct"] * 100, 1),
    }


def infer_dataset_semantics(df: pd.DataFrame, overrides: dict[str, str] | None = None) -> dict[str, dict]:
    """
    Infer semantics for all columns in a dataframe, applying any user overrides.
    Returns: {col_name: {semantic_type, confidence, evidence, needs_confirmation, ...}}
    """
    overrides = overrides or {}
    results = {}
    for col in df.columns:
        col_str = str(col)
        res = infer_column_semantic_type(col_str, df[col])
        if col_str in overrides:
            user_type = overrides[col_str]
            res["semantic_type"] = user_type
            res["confidence"] = 1.0
            res["evidence"] = f"User override applied: {user_type} (auto-detected: {res.get('name_hint') or 'inferred'})"
            res["needs_confirmation"] = False
            res["is_override"] = True
        results[col_str] = res
    return results
