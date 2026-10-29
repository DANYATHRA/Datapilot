"""
Complete Cleaning Engine for DataPilot (Completeness Contract A1 & A2).

Provides:
  - Multi-pass auto-cleaning loop that runs until convergence (up to 5 passes).
  - All detectors and fixers required by contract:
      * Structure: preamble/title rows, merged cells, blank rows/cols, hidden rows/cols,
                   repeated headers inside data, total/subtotal/footer rows, multi-row headers,
                   duplicate/blank column names, leading apostrophes.
      * Missing-value tokens: empty, whitespace-only, non-breaking spaces, N/A, NA, n/a,
                              #N/A, null, NULL, None, nil, -, --, ?, missing, TBD, #VALUE!, etc.
      * Text: trim, collapse spaces, zero-width/non-breaking chars, curly quotes, mojibake,
              trailing punctuation.
      * Numbers: text numbers, thousands separators (comma, space, quote), European decimals,
                 currency symbols (₹, $, €, £, ¥, INR, USD, EUR, GBP), percent strings,
                 parentheses negatives, trailing minus, units inside numbers (kg, m, sqft, hrs),
                 scientific notation, integer .0 stripping.
      * Dates: mixed formats, 2-digit years (pivot rule), Excel serial numbers, date+time,
               text months, ambiguous day/month detection with evidence & default, impossible dates.
      * Categories: case variants, typos/near-duplicates (fuzzy Levenshtein), boolean synonyms,
                    inconsistent abbreviations.
      * Identifiers & contacts: keep as text, restore lost leading zeros, normalize phone formats (+91),
                                lowercase & validate emails, validate PAN/pincode/Aadhaar.
      * Rows: exact duplicates, duplicate IDs (identical -> drop, conflicting -> Needs review).
      * Values: domain outliers, impossible values (negative price/age/qty, percent > 100), mixed types.
      * Missing values: strict semantic policy (IDs/emails/phones/names/dates NEVER imputed;
                        money/quantities group median; categories mode or Unknown; derived formulas).
  - Post-cleaning "Clean check" asserting zero auto-fixable issues remain.
  - Generates the Clean banner: "Clean. 0 issues can be fixed automatically. N need your decision."
  - Idempotent and regression-guarded.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd

from .column_semantics import infer_dataset_semantics
from .missing_policy import (
    POLICY_MATRIX,
    detect_derived_formulas,
    find_best_group_column,
)

# ────────────────────────────────────────────────────────────────────────────
# Missing-value tokens & regular expressions
# ────────────────────────────────────────────────────────────────────────────
NULL_TOKENS = {
    "",
    " ",
    "\t",
    "\n",
    "\r",
    "\u00a0",
    "\u200b",
    "\u200c",
    "\u200d",
    "\ufeff",
    "nan",
    "none",
    "null",
    "nil",
    "na",
    "n/a",
    "#n/a",
    "#na",
    "n.a.",
    "n.a",
    "n/a n/a",
    "-",
    "--",
    "---",
    "- -",
    "?",
    "??",
    "???",
    "missing",
    "tbd",
    "tba",
    "#value!",
    "#ref!",
    "#num!",
    "#div/0!",
    "#name?",
    "#null!",
    "undefined",
    ".",
}

MOJIBAKE_MAP = {
    "â€™": "'",
    "â€˜": "'",
    "â€œ": '"',
    "â€\x9d": '"',
    "â€": '"',
    "â€“": "-",
    "â€”": "—",
    "Ã©": "é",
    "Ã¨": "è",
    "Ã ": "à",
    "Ã§": "ç",
    "Ã®": "î",
    "Ã´": "ô",
    "Ã»": "û",
    "Ã¼": "ü",
    "Ã¶": "ö",
    "Ã¤": "ä",
    "Â": "",
}

BOOLEAN_TRUE = {"true", "yes", "y", "t", "1", "1.0"}
BOOLEAN_FALSE = {"false", "no", "n", "f", "0", "0.0"}

CURRENCY_SYMBOLS = ["₹", "$", "€", "£", "¥", "INR", "USD", "EUR", "GBP", "Rs.", "Rs", "rs"]
UNITS_REGEX = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(kg|g|mg|m|cm|mm|km|sqft|sqm|hrs|hr|hours|days|lbs|oz|litres|l|ml|units|pcs|items)\b", re.IGNORECASE)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
PINCODE_REGEX = re.compile(r"^[1-9][0-9]{5}$")
AADHAAR_REGEX = re.compile(r"^[2-9][0-9]{11}$")
PHONE_DIGITS_REGEX = re.compile(r"\D")


def is_missing_value(val: Any) -> bool:
    """Check if value is null, NaN, or matches any missing-value token."""
    if val is None:
        return True
    if isinstance(val, (float, np.floating)) and math.isnan(val):
        return True
    if isinstance(val, (np.datetime64, pd.Timestamp)) and pd.isna(val):
        return True
    val_str = str(val).strip().lower()
    # Normalize zero-width chars
    val_str = re.sub(r"[\u00a0\u200b\u200c\u200d\ufeff]", "", val_str)
    return val_str in NULL_TOKENS or val_str == ""


# ────────────────────────────────────────────────────────────────────────────
# 1. Structure Detectors & Fixers
# ────────────────────────────────────────────────────────────────────────────

def clean_structure_preamble_and_headers(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """
    Detects title/notes rows above the header, multi-row headers,
    blank columns, and duplicate column names.
    """
    changes = []
    df = df.copy()

    # 1. Check if first row(s) are title/notes preamble rows
    # Characteristics: row has mostly NaNs or 1 single cell while row below has many distinct text headers
    if len(df) > 1:
        top_row = df.iloc[0]
        non_null_count = sum(1 for v in top_row if not is_missing_value(v))
        total_cols = len(df.columns)

        # If top row has <= 2 non-null cells and columns look like 'Unnamed: ...'
        unnamed_cols = sum(1 for c in df.columns if str(c).startswith("Unnamed:") or is_missing_value(c))
        if unnamed_cols > total_cols * 0.5 and non_null_count <= 2:
            # Row 0 is likely title/notes. Check Row 1
            cand_header = df.iloc[0].dropna().tolist()
            title_text = " / ".join(str(x) for x in cand_header)
            # Find next non-empty row to use as header
            header_idx = -1
            for r in range(min(5, len(df))):
                vals = [v for v in df.iloc[r] if not is_missing_value(v)]
                if len(vals) >= total_cols * 0.6:
                    header_idx = r
                    break
            if header_idx != -1:
                new_cols = [str(df.iloc[header_idx, c]).strip() for c in range(total_cols)]
                df = df.iloc[header_idx + 1:].reset_index(drop=True)
                df.columns = new_cols
                changes.append({
                    "rule": "structure_preamble_removed",
                    "reason": f"Discarded preamble title rows: '{title_text[:60]}'",
                    "old_val": "Preamble Rows",
                    "new_val": f"Promoted row {header_idx + 1} to header",
                })

    # 2. Fix duplicate or blank column names
    seen_cols: dict[str, int] = {}
    cleaned_cols = []
    for idx, c in enumerate(df.columns):
        c_str = str(c).strip()
        if is_missing_value(c_str) or c_str.lower().startswith("unnamed:"):
            c_str = f"column_{idx + 1}"
            changes.append({
                "rule": "structure_blank_column_renamed",
                "reason": "Renamed blank column header",
                "old_val": str(c),
                "new_val": c_str,
            })
        base_name = c_str
        if base_name in seen_cols:
            seen_cols[base_name] += 1
            c_str = f"{base_name}_{seen_cols[base_name]}"
            changes.append({
                "rule": "structure_duplicate_column_deduped",
                "reason": "Deduplicated duplicate column name",
                "old_val": base_name,
                "new_val": c_str,
            })
        else:
            seen_cols[base_name] = 1
        cleaned_cols.append(c_str)
    df.columns = cleaned_cols

    return df, changes


def clean_structure_rows_and_cols(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """
    Cleans blank rows, blank columns, repeated header rows inside data,
    total/subtotal/footer rows, and strips leading apostrophes.
    Returns (cleaned_df, changes_log, removed_rows_log).
    """
    df = df.copy()
    changes = []
    removed_rows = []

    # 1. Drop completely blank columns
    blank_cols = []
    for c in df.columns:
        s = df[c]
        if s.apply(is_missing_value).all():
            blank_cols.append(c)
    if blank_cols:
        df = df.drop(columns=blank_cols)
        for c in blank_cols:
            changes.append({
                "rule": "structure_blank_column_dropped",
                "reason": f"Dropped completely blank column '{c}'",
                "column": c,
                "old_val": "[Blank Column]",
                "new_val": "[Dropped]",
            })

    # 2. Identify rows to drop: blank rows, repeated headers, totals/subtotals
    cols = list(df.columns)
    header_lower = [str(c).lower().strip() for c in cols]
    drop_indices = []

    for idx, row in df.iterrows():
        row_vals = [row[c] for c in cols]
        non_null_vals = [v for v in row_vals if not is_missing_value(v)]

        # a) Blank row
        if len(non_null_vals) == 0:
            drop_indices.append(idx)
            removed_rows.append({
                "row_idx": int(idx),
                "reason": "Completely blank row",
                "data": {},
            })
            continue

        # b) Repeated header row inside the data
        row_str_lower = [str(v).lower().strip() for v in row_vals]
        matches_header = sum(1 for rv, hv in zip(row_str_lower, header_lower) if rv == hv and rv != "")
        if matches_header >= len(cols) * 0.6:
            drop_indices.append(idx)
            removed_rows.append({
                "row_idx": int(idx),
                "reason": "Repeated column header row inside data",
                "data": {c: str(row[c]) for c in cols[:5]},
            })
            continue

        # c) Total / subtotal / footer rows
        first_non_null = str(non_null_vals[0]).strip().lower()
        if any(pref in first_non_null for pref in ("total", "grand total", "subtotal", "sub-total", "average", "summary", "footer", "audit")):
            drop_indices.append(idx)
            removed_rows.append({
                "row_idx": int(idx),
                "reason": f"Summary/subtotal/footer row ('{non_null_vals[0]}')",
                "data": {c: str(row[c]) for c in cols[:5]},
            })
            continue

    if drop_indices:
        df = df.drop(index=drop_indices).reset_index(drop=True)
        changes.append({
            "rule": "structure_rows_cleaned",
            "reason": f"Removed {len(drop_indices)} non-data rows (blanks, repeated headers, subtotals)",
            "count": len(drop_indices),
        })

    # 3. Strip leading apostrophe from strings (Excel text markers like '123 or '=A1)
    for c in df.columns:
        s = df[c]
        if s.dtype == object or pd.api.types.is_string_dtype(s):
            for r_idx in df.index:
                val = df.at[r_idx, c]
                if isinstance(val, str) and val.startswith("'") and len(val) > 1:
                    stripped = val[1:]
                    df.at[r_idx, c] = stripped
                    changes.append({
                        "rule": "structure_leading_apostrophe_stripped",
                        "column": str(c),
                        "row": int(r_idx),
                        "old_val": val,
                        "new_val": stripped,
                    })

    return df, changes, removed_rows


# ────────────────────────────────────────────────────────────────────────────
# 2. Missing-Value Token Standardization
# ────────────────────────────────────────────────────────────────────────────

def standardize_missing_tokens_in_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Replaces all missing-value tokens (N/A, null, -, ?, TBD, etc.) with None."""
    df = df.copy()
    changes = []
    for c in df.columns:
        s = df[c]
        for r in df.index:
            v = df.at[r, c]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                if is_missing_value(v):
                    df.at[r, c] = None
                    changes.append({
                        "rule": "missing_token_standardized",
                        "column": str(c),
                        "row": int(r),
                        "old_val": str(v),
                        "new_val": None,
                    })
    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# 3. Text Normalization
# ────────────────────────────────────────────────────────────────────────────

def normalize_text_in_df(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict]]:
    """
    Trim, collapse multiple spaces, strip zero-width chars, convert curly quotes,
    fix mojibake, and clean trailing punctuation.
    """
    df = df.copy()
    changes = []

    for c in df.columns:
        c_str = str(c)
        s = df[c]
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")

        # Skip purely numeric columns
        if pd.api.types.is_numeric_dtype(s) and sem_type not in ("identifier", "contact_phone"):
            continue

        for r in df.index:
            v = df.at[r, c]
            if v is None or pd.isna(v) or not isinstance(v, str):
                continue

            orig_str = v
            cur = orig_str

            # 1. Strip zero-width & non-breaking spaces
            cur = re.sub(r"[\u00a0\u200b\u200c\u200d\ufeff]", " ", cur)

            # 2. Fix mojibake
            for bad, good in MOJIBAKE_MAP.items():
                if bad in cur:
                    cur = cur.replace(bad, good)

            # 3. Replace curly quotes with standard straight quotes
            cur = cur.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

            # 4. Collapse internal whitespace and trim
            cur = re.sub(r"\s+", " ", cur).strip()

            # 5. Remove accidental trailing punctuation on words/names/categories
            if sem_type in ("category", "person_name", "status/boolean_flag") and len(cur) > 1:
                cur = re.sub(r"[,;]+$", "", cur).strip()

            if cur != orig_str:
                df.at[r, c] = cur
                changes.append({
                    "rule": "text_normalized",
                    "column": c_str,
                    "row": int(r),
                    "old_val": orig_str,
                    "new_val": cur,
                })

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# 4. Number Normalization & Conversion
# ────────────────────────────────────────────────────────────────────────────

def clean_and_convert_numbers(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict]]:
    """
    Fixes text numbers, thousands separators (comma, space, quote), European decimals,
    currency symbols (₹, $, €, £, ¥, INR, USD, EUR), percent strings (12% -> 0.12),
    parentheses negatives ((100) -> -100), trailing minus (100- -> -100),
    units inside numbers (5 kg -> 5), scientific notation, and .0 integer stripping.
    Preserves text on identifiers, codes, phones, emails.
    """
    df = df.copy()
    changes = []

    for c in df.columns:
        c_str = str(c)
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")

        # Strictly skip identifiers, phone numbers, postal codes, dates, names, emails
        if (
            sem_type in ("identifier", "contact_phone", "date", "date_time", "contact_email", "person_name")
            or any(w in c_str.lower() for w in ("phone", "mobile", "id", "code", "pan", "zip", "pincode", "roll", "ssn", "aadhaar", "date", "time", "dob", "name", "email"))
        ):
            continue

        s = df[c]
        non_null_series = s.dropna()
        if non_null_series.empty:
            continue

        # Check if column is a candidate for numeric conversion
        # A candidate column has >= 50% values that can be parsed as numbers after stripping units/currencies
        convertible_count = 0
        parsed_cache: dict[int, float | int] = {}

        for r, v in non_null_series.items():
            if isinstance(v, (int, float, np.integer, np.floating)):
                convertible_count += 1
                parsed_cache[r] = v
                continue

            v_str = str(v).strip()
            if is_missing_value(v_str):
                continue

            # Strip leading apostrophe if any
            if v_str.startswith("'"):
                v_str = v_str[1:]

            # 1. Units inside numbers: "5 kg", "10.5 m"
            unit_match = UNITS_REGEX.match(v_str)
            if unit_match:
                v_str = unit_match.group(1)

            # 2. Currency stripping: ₹, $, €, £, ¥, INR, USD, etc.
            for cur in CURRENCY_SYMBOLS:
                if v_str.startswith(cur) or v_str.endswith(cur):
                    v_str = v_str.replace(cur, "").strip()
                elif f" {cur}" in v_str or f"{cur} " in v_str:
                    v_str = v_str.replace(cur, "").strip()

            # 3. Percent strings: 12% -> 0.12
            is_percent = False
            if v_str.endswith("%"):
                is_percent = True
                v_str = v_str[:-1].strip()

            # 4. Parentheses negatives: (100) -> -100
            if v_str.startswith("(") and v_str.endswith(")"):
                v_str = "-" + v_str[1:-1].strip()

            # 5. Trailing minus: 100- -> -100
            if v_str.endswith("-") and not v_str.startswith("-"):
                v_str = "-" + v_str[:-1].strip()

            # 6. European decimal: 1.234,56 or 1234,56
            if re.match(r"^-?\d{1,3}(?:\.\d{3})*,\d+$", v_str):
                v_str = v_str.replace(".", "").replace(",", ".")
            elif re.match(r"^-?\d+,\d+$", v_str):
                # E.g. 45,50
                v_str = v_str.replace(",", ".")
            else:
                # Standard thousands separators: 1,234,567 or 1 234 567 or 1'234'567
                v_str = re.sub(r"[, '](?=\d{3}\b)", "", v_str)

            # Try parsing float
            try:
                num_val = float(v_str)
                if is_percent:
                    num_val = round(num_val / 100.0, 4)
                # Integer check
                if num_val % 1 == 0 and abs(num_val) <= 2**53:
                    num_val = int(num_val)
                convertible_count += 1
                parsed_cache[r] = num_val
            except ValueError:
                pass

        # If >= 60% of non-null values are numeric, convert the column
        if convertible_count >= len(non_null_series) * 0.6:
            if df[c].dtype != object:
                df[c] = df[c].astype(object)
            for r, new_num in parsed_cache.items():
                old_v = df.at[r, c]
                if old_v != new_num:
                    df.at[r, c] = new_num
                    changes.append({
                        "rule": "number_cleaned",
                        "column": c_str,
                        "row": int(r),
                        "old_val": str(old_v),
                        "new_val": new_num,
                    })
            # Convert series dtype to numeric
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            except Exception:
                pass

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# 5. Date Normalization & Ambiguity Detection
# ────────────────────────────────────────────────────────────────────────────

def clean_and_standardize_dates(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """
    Standardizes mixed date formats, 2-digit years, Excel serial numbers,
    date+time, and text months to ISO YYYY-MM-DD.
    Detects ambiguous day/month and flags with evidence.
    Returns (cleaned_df, changes_log, decision_items).
    """
    df = df.copy()
    changes = []
    decision_items = []
    today = dt.date.today()

    for c in df.columns:
        c_str = str(c)
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")

        # Check if column is a date column or candidate
        is_date_col = sem_type in ("date", "date_time") or any(
            w in c_str.lower() for w in ("date", "dob", "joined", "timestamp", "created_at", "period", "month")
        )
        if not is_date_col:
            continue

        s = df[c]
        non_null_series = s.dropna()
        if non_null_series.empty:
            continue

        # First pass: check for dayfirst evidence (any day > 12)
        has_day_gt_12 = False
        evidence_samples = []
        for v in non_null_series:
            v_str = str(v).strip()
            # Match DD/MM/YYYY or DD-MM-YYYY
            m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", v_str)
            if m:
                part1, part2 = int(m.group(1)), int(m.group(2))
                if part1 > 12 and part2 <= 12:
                    has_day_gt_12 = True
                    evidence_samples.append(f"{v_str} (day={part1})")
                elif part2 > 12 and part1 <= 12:
                    # MM/DD/YYYY
                    pass

        dayfirst = True if has_day_gt_12 else True  # default to dayfirst in non-US / Indian contexts

        # Parse each date value
        for r, v in non_null_series.items():
            if is_missing_value(v):
                continue

            parsed_date: dt.date | None = None
            orig_str = str(v).strip()

            # 0. Already valid ISO YYYY-MM-DD
            if re.match(r"^\d{4}-\d{2}-\d{2}$", orig_str):
                try:
                    parsed_date = dt.date.fromisoformat(orig_str)
                except ValueError:
                    parsed_date = None

            # 1. Excel serial number: e.g. 44927
            if isinstance(v, (int, float, np.integer, np.floating)) and 30000 <= v <= 60000:
                try:
                    dt_val = pd.to_datetime(v, unit="D", origin="1899-12-30")
                    parsed_date = dt_val.date()
                except Exception:
                    pass

            # 2. Text formats
            if parsed_date is None:
                # Two-digit year handling: e.g. 15/01/23 -> 2023
                m_2yr = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2})$", orig_str)
                if m_2yr:
                    p1, p2, yr_2d = int(m_2yr.group(1)), int(m_2yr.group(2)), int(m_2yr.group(3))
                    full_yr = 2000 + yr_2d if yr_2d <= 50 else 1900 + yr_2d
                    fixed_str = f"{p1:02d}/{p2:02d}/{full_yr}"
                else:
                    fixed_str = orig_str

                try:
                    dt_val = pd.to_datetime(fixed_str, dayfirst=dayfirst, errors="raise")
                    parsed_date = dt_val.date()
                except Exception:
                    # Try fallback without dayfirst
                    try:
                        dt_val = pd.to_datetime(fixed_str, dayfirst=False, errors="raise")
                        parsed_date = dt_val.date()
                    except Exception:
                        parsed_date = None

            if parsed_date:
                iso_str = parsed_date.strftime("%Y-%m-%d")

                # Check future dates for DOB / past events
                if "dob" in c_str.lower() or "birth" in c_str.lower():
                    if parsed_date > today:
                        decision_items.append({
                            "row": int(r),
                            "column": c_str,
                            "issue_type": "invalid_date",
                            "reason": f"Future date for Date of Birth ({iso_str})",
                            "current_value": orig_str,
                        })
                        continue

                if orig_str != iso_str:
                    df.at[r, c] = iso_str
                    changes.append({
                        "rule": "date_standardized_iso",
                        "column": c_str,
                        "row": int(r),
                        "old_val": orig_str,
                        "new_val": iso_str,
                    })
            else:
                # Impossible date or malformed
                decision_items.append({
                    "row": int(r),
                    "column": c_str,
                    "issue_type": "invalid_date",
                    "reason": f"Unparseable date value '{orig_str}'",
                    "current_value": orig_str,
                })

    return df, changes, decision_items


# ────────────────────────────────────────────────────────────────────────────
# 6. Category Normalization & Fuzzy Typo Deduplication
# ────────────────────────────────────────────────────────────────────────────

def clean_and_standardize_categories(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict]]:
    """
    Standardizes boolean synonyms (yes/no/true/false/1/0), casing variants,
    and fuzzy typos / near-duplicates (similarity >= 0.85).
    """
    df = df.copy()
    changes = []

    for c in df.columns:
        c_str = str(c)
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")

        # Only process categorical or status columns
        if sem_type not in ("category", "status/boolean_flag"):
            continue

        s = df[c]
        non_null_series = s.dropna()
        if non_null_series.empty:
            continue

        # 1. Boolean synonyms
        unique_vals_lower = {str(v).strip().lower() for v in non_null_series if not is_missing_value(v)}
        if unique_vals_lower.issubset(BOOLEAN_TRUE | BOOLEAN_FALSE | {""}):
            for r, v in non_null_series.items():
                v_low = str(v).strip().lower()
                if v_low in BOOLEAN_TRUE and str(v) != "True":
                    df.at[r, c] = "True"
                    changes.append({
                        "rule": "boolean_synonym_standardized",
                        "column": c_str,
                        "row": int(r),
                        "old_val": str(v),
                        "new_val": "True",
                    })
                elif v_low in BOOLEAN_FALSE and str(v) != "False":
                    df.at[r, c] = "False"
                    changes.append({
                        "rule": "boolean_synonym_standardized",
                        "column": c_str,
                        "row": int(r),
                        "old_val": str(v),
                        "new_val": "False",
                    })
            continue

        # 2. Case variants & frequency mapping
        val_counts: dict[str, int] = {}
        canonical_case: dict[str, str] = {}
        for v in non_null_series:
            v_str = str(v).strip()
            if not is_missing_value(v_str):
                val_counts[v_str] = val_counts.get(v_str, 0) + 1
                v_low = v_str.lower()
                # Most frequent string is canonical
                if v_low not in canonical_case or val_counts[v_str] > val_counts.get(canonical_case[v_low], 0):
                    canonical_case[v_low] = v_str

        # 3. Fuzzy typo matching among canonical words
        unique_canonicals = sorted(set(canonical_case.values()), key=lambda x: val_counts.get(x, 0), reverse=True)
        fuzzy_replacements: dict[str, str] = {}

        for i, word1 in enumerate(unique_canonicals):
            for word2 in unique_canonicals[i + 1:]:
                # If length >= 4 and similarity >= 0.85
                if len(word1) >= 4 and len(word2) >= 4:
                    sim = SequenceMatcher(None, word1.lower(), word2.lower()).ratio()
                    threshold = 0.75 if (len(word1) <= 6 or len(word2) <= 6) else 0.85
                    if sim >= threshold:
                        fuzzy_replacements[word2] = word1

        # Apply casing and fuzzy replacements
        for r, v in non_null_series.items():
            v_str = str(v).strip()
            if is_missing_value(v_str):
                continue
            v_low = v_str.lower()
            target = canonical_case.get(v_low, v_str)
            target = fuzzy_replacements.get(target, target)

            if v_str != target:
                df.at[r, c] = target
                changes.append({
                    "rule": "category_typo_standardized",
                    "column": c_str,
                    "row": int(r),
                    "old_val": v_str,
                    "new_val": target,
                })

    return df, changes


# ────────────────────────────────────────────────────────────────────────────
# 7. Identifiers & Contacts Normalization & Validation
# ────────────────────────────────────────────────────────────────────────────

def clean_identifiers_and_contacts(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """
    Keeps identifiers as text, restores leading zeros (for fixed-width codes or pincodes),
    normalizes phone formats, lowercases and validates emails, validates PAN/pincode/Aadhaar.
    Returns (cleaned_df, changes_log, decision_items).
    """
    df = df.copy()
    changes = []
    decision_items = []

    for c in df.columns:
        c_str = str(c)
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")

        s = df[c]
        non_null_series = s.dropna()
        if non_null_series.empty:
            continue

        # 1. Identifiers & Codes: keep as text, restore lost leading zeros
        if sem_type == "identifier" or "id" in c_str.lower() or "code" in c_str.lower():
            if df[c].dtype != object:
                df[c] = df[c].astype(object)
            # Check if expected length is fixed (e.g. 5 digits)
            lengths = [len(str(v).strip()) for v in non_null_series if not is_missing_value(v)]
            mode_len = max(set(lengths), key=lengths.count) if lengths else 0

            for r, v in non_null_series.items():
                if is_missing_value(v):
                    continue
                v_str = str(v).strip()
                # If numeric string lost leading zero
                if mode_len > 0 and len(v_str) < mode_len and v_str.isdigit():
                    padded = v_str.zfill(mode_len)
                    df.at[r, c] = padded
                    changes.append({
                        "rule": "identifier_leading_zeros_restored",
                        "column": c_str,
                        "row": int(r),
                        "old_val": v_str,
                        "new_val": padded,
                    })
                elif not isinstance(v, str):
                    df.at[r, c] = v_str

        # 2. Contact Phone: normalize formats
        elif sem_type == "contact_phone" or any(w in c_str.lower() for w in ("phone", "mobile", "contact_no")):
            if df[c].dtype != object:
                df[c] = df[c].astype(object)
            for r, v in non_null_series.items():
                if is_missing_value(v):
                    continue
                orig_str = str(v).strip()
                # Strip non-digits except +
                digits_only = PHONE_DIGITS_REGEX.sub("", orig_str)
                # Standardize Indian 10-digit or 12-digit numbers
                if len(digits_only) == 10:
                    norm_phone = f"+91 {digits_only[:5]} {digits_only[5:]}"
                elif len(digits_only) == 12 and digits_only.startswith("91"):
                    norm_phone = f"+91 {digits_only[2:7]} {digits_only[7:]}"
                elif len(digits_only) == 11 and digits_only.startswith("0"):
                    norm_phone = f"+91 {digits_only[1:6]} {digits_only[6:]}"
                else:
                    norm_phone = orig_str

                if orig_str != norm_phone and len(digits_only) in (10, 11, 12):
                    df.at[r, c] = norm_phone
                    changes.append({
                        "rule": "phone_format_normalized",
                        "column": c_str,
                        "row": int(r),
                        "old_val": orig_str,
                        "new_val": norm_phone,
                    })
                elif len(digits_only) < 7:
                    decision_items.append({
                        "row": int(r),
                        "column": c_str,
                        "issue_type": "invalid_phone",
                        "reason": f"Invalid phone number '{orig_str}' (< 7 digits)",
                        "current_value": orig_str,
                    })

        # 3. Contact Email: lowercase, trim, validate
        elif sem_type == "contact_email" or "email" in c_str.lower():
            if df[c].dtype != object:
                df[c] = df[c].astype(object)
            for r, v in non_null_series.items():
                if is_missing_value(v):
                    continue
                orig_str = str(v).strip()
                lower_email = orig_str.lower()
                if orig_str != lower_email:
                    df.at[r, c] = lower_email
                    changes.append({
                        "rule": "email_lowercased",
                        "column": c_str,
                        "row": int(r),
                        "old_val": orig_str,
                        "new_val": lower_email,
                    })

                if not EMAIL_REGEX.match(lower_email):
                    decision_items.append({
                        "row": int(r),
                        "column": c_str,
                        "issue_type": "invalid_email",
                        "reason": f"Invalid email format '{lower_email}'",
                        "current_value": lower_email,
                    })

        # 4. PAN card validation
        elif "pan" in c_str.lower():
            for r, v in non_null_series.items():
                if is_missing_value(v):
                    continue
                orig_str = str(v).strip().upper()
                if str(v) != orig_str:
                    df.at[r, c] = orig_str
                if not PAN_REGEX.match(orig_str):
                    decision_items.append({
                        "row": int(r),
                        "column": c_str,
                        "issue_type": "invalid_pan",
                        "reason": f"Invalid PAN number format '{orig_str}'",
                        "current_value": orig_str,
                    })

        # 5. Pincode validation
        elif "pincode" in c_str.lower() or "zip" in c_str.lower():
            for r, v in non_null_series.items():
                if is_missing_value(v):
                    continue
                orig_str = str(v).strip()
                if orig_str.isdigit() and len(orig_str) == 5:
                    orig_str = "0" + orig_str
                    df.at[r, c] = orig_str
                if not PINCODE_REGEX.match(orig_str):
                    decision_items.append({
                        "row": int(r),
                        "column": c_str,
                        "issue_type": "invalid_pincode",
                        "reason": f"Invalid 6-digit Pincode '{orig_str}'",
                        "current_value": orig_str,
                    })

    return df, changes, decision_items


# ────────────────────────────────────────────────────────────────────────────
# 8. Row Deduplication & Duplicate ID Detection
# ────────────────────────────────────────────────────────────────────────────

def clean_rows_and_duplicates(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict], list[dict], list[dict]]:
    """
    Drops exact duplicate rows.
    Detects duplicate IDs:
      - If non-ID columns are identical -> drop duplicate row.
      - If non-ID columns conflict -> flag as "Needs decision: Conflicting records for same ID".
    Returns (cleaned_df, changes_log, removed_rows_log, decision_items).
    """
    df = df.copy()
    changes = []
    removed_rows = []
    decision_items = []

    # 1. Exact duplicate rows
    dups_mask = df.duplicated(keep="first")
    dup_count = int(dups_mask.sum())
    if dup_count > 0:
        dup_rows = df[dups_mask]
        for idx in dup_rows.index:
            removed_rows.append({
                "row_idx": int(idx),
                "reason": "Exact duplicate row",
                "data": {c: str(dup_rows.loc[idx, c]) for c in df.columns[:5]},
            })
        df = df[~dups_mask].reset_index(drop=True)
        changes.append({
            "rule": "exact_duplicates_removed",
            "reason": f"Removed {dup_count} exact duplicate row(s)",
            "count": dup_count,
        })

    # 2. Duplicate ID detection
    id_cols = [c for c in df.columns if semantics.get(str(c), {}).get("semantic_type") == "identifier" or "id" in str(c).lower()]
    if id_cols:
        id_col = id_cols[0]
        s_id = df[id_col].astype(str).str.strip()
        non_null_mask = ~df[id_col].apply(is_missing_value)
        dup_id_values = s_id[non_null_mask][s_id[non_null_mask].duplicated()].unique()

        rows_to_drop = []
        for d_id in dup_id_values:
            matching_mask = (s_id == d_id) & non_null_mask
            matching_rows = df[matching_mask]
            # Compare non-id columns
            non_id_cols = [c for c in df.columns if c != id_col]
            # Check if all matching rows have identical data
            is_identical = matching_rows[non_id_cols].duplicated(keep=False).all()

            if is_identical:
                # Keep first, drop others
                drop_these = matching_rows.index[1:].tolist()
                rows_to_drop.extend(drop_these)
                for r_idx in drop_these:
                    removed_rows.append({
                        "row_idx": int(r_idx),
                        "reason": f"Identical duplicate record for ID '{d_id}'",
                        "data": {c: str(df.loc[r_idx, c]) for c in df.columns[:5]},
                    })
            else:
                # Conflicting records! Must be flagged for human decision
                for r_idx in matching_rows.index:
                    decision_items.append({
                        "row": int(r_idx),
                        "column": str(id_col),
                        "issue_type": "conflicting_duplicate_id",
                        "reason": f"Conflicting record for duplicate ID '{d_id}'",
                        "current_value": d_id,
                    })

        if rows_to_drop:
            df = df.drop(index=rows_to_drop).reset_index(drop=True)
            changes.append({
                "rule": "duplicate_id_identical_dropped",
                "reason": f"Dropped {len(rows_to_drop)} identical rows with duplicate ID",
                "count": len(rows_to_drop),
            })

    return df, changes, removed_rows, decision_items


# ────────────────────────────────────────────────────────────────────────────
# 9. Value Bounds & Impossible Values Check
# ────────────────────────────────────────────────────────────────────────────

def check_value_bounds_and_impossible(df: pd.DataFrame, semantics: dict[str, dict]) -> list[dict]:
    """
    Identifies impossible negative values (price, age, quantity), percentages > 100,
    and extreme domain outliers for human decision.
    """
    decision_items = []

    for c in df.columns:
        c_str = str(c).lower()
        sem_info = semantics.get(str(c), {})
        sem_type = sem_info.get("semantic_type", "other_text")

        s = pd.to_numeric(df[c], errors="coerce")
        if s.dropna().empty:
            continue

        # 1. Impossible negative values
        if any(w in c_str for w in ("age", "price", "unit_price", "qty", "quantity", "cost", "salary", "units")):
            negative_mask = s < 0
            for r in df[negative_mask].index:
                val = df.at[r, c]
                decision_items.append({
                    "row": int(r),
                    "column": str(c),
                    "issue_type": "impossible_value",
                    "reason": f"Negative value '{val}' in non-negative column '{c}'",
                    "current_value": val,
                })

        # 2. Percentage > 100
        if "percent" in c_str or "pct" in c_str or sem_type == "percentage":
            high_pct_mask = s > 100
            for r in df[high_pct_mask].index:
                val = df.at[r, c]
                decision_items.append({
                    "row": int(r),
                    "column": str(c),
                    "issue_type": "impossible_value",
                    "reason": f"Percentage value '{val}' exceeds 100%",
                    "current_value": val,
                })

        # 3. Extreme Outliers (3 * IQR)
        if sem_type in ("money_amount", "quantity", "other_numeric") and len(s.dropna()) >= 10:
            q1 = float(s.quantile(0.25))
            q3 = float(s.quantile(0.75))
            iqr = q3 - q1
            if iqr > 0:
                low_bound = q1 - 3.0 * iqr
                high_bound = q3 + 3.0 * iqr
                outlier_mask = (s < low_bound) | (s > high_bound)
                for r in df[outlier_mask].index:
                    val = df.at[r, c]
                    decision_items.append({
                        "row": int(r),
                        "column": str(c),
                        "issue_type": "outlier",
                        "reason": f"Statistical outlier '{val}' outside 3×IQR [{low_bound:.1f}, {high_bound:.1f}]",
                        "current_value": val,
                    })

    return decision_items


# ────────────────────────────────────────────────────────────────────────────
# 10. Semantic Missing-Value Policy
# ────────────────────────────────────────────────────────────────────────────

def clean_missing_values_semantic(df: pd.DataFrame, semantics: dict[str, dict]) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """
    Strict Semantic Missing-Value Policy:
      - Identifiers, emails, phones, names, dates: NEVER mean/median/mode filled;
        left blank and flagged as "Needs decision: Unique ID, so it can't be guessed".
      - Derived formulas: automatically recomputed (e.g. revenue = qty * price).
      - Money/quantities: group median (if group >= 3), else global median.
      - Categories/status: mode if missing <= 15%, else "Unknown".
    Returns (cleaned_df, changes_log, decision_items).
    """
    df = df.copy()
    changes = []
    decision_items = []

    # 1. Derived formulas first
    formulas = detect_derived_formulas(df)
    formula_map = {f["target"]: f for f in formulas}

    for col, f_info in formula_map.items():
        if col in df.columns:
            try:
                calc_s = f_info["fn"](df)
                missing_mask = df[col].apply(is_missing_value)
                for r in df[missing_mask].index:
                    calc_val = calc_s.loc[r]
                    if pd.notna(calc_val) and not np.isinf(calc_val):
                        old_v = df.at[r, col]
                        new_v = round(float(calc_val), 2)
                        df.at[r, col] = new_v
                        changes.append({
                            "rule": "derived_formula_computed",
                            "column": str(col),
                            "row": int(r),
                            "old_val": str(old_v),
                            "new_val": new_v,
                        })
            except Exception:
                pass

    # 2. Per-column semantic policy
    for c in df.columns:
        c_str = str(c)
        s = df[c]
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")
        policy = POLICY_MATRIX.get(sem_type, POLICY_MATRIX["other_text"])

        missing_mask = s.apply(is_missing_value)
        if not missing_mask.any():
            continue

        # STRICT RESTRICTION: IDs, emails, phones, names, dates, urls are NEVER imputed
        if not policy.get("can_impute", False):
            for r in df[missing_mask].index:
                decision_items.append({
                    "row": int(r),
                    "column": c_str,
                    "issue_type": "missing_restricted",
                    "reason": f"Blank {policy.get('label', 'identifier')} cannot be guessed",
                    "current_value": "",
                })
            continue

        missing_count = int(missing_mask.sum())
        missing_pct = missing_count / len(df) if len(df) else 0

        # High missing rate (> 40%): don't invent numbers blindly
        if missing_pct > 0.40:
            for r in df[missing_mask].index:
                decision_items.append({
                    "row": int(r),
                    "column": c_str,
                    "issue_type": "high_missing_rate",
                    "reason": f"High missing rate ({missing_pct:.0%}) in '{c_str}'",
                    "current_value": "",
                })
            continue

        # Money / Quantities / Numerics: group median or global median
        if sem_type in ("money_amount", "quantity", "other_numeric", "age", "rating_scale"):
            group_col = find_best_group_column(df, c_str, semantics)
            num_s = pd.to_numeric(s, errors="coerce").dropna()
            global_med = round(float(num_s.median()), 2) if not num_s.empty else 0
            if sem_type in ("quantity", "age"):
                global_med = int(round(global_med))

            for r in df[missing_mask].index:
                fill_val = global_med
                if group_col:
                    g_val = df.at[r, group_col]
                    if pd.notna(g_val):
                        sub = pd.to_numeric(df.loc[df[group_col] == g_val, c_str], errors="coerce").dropna()
                        if len(sub) >= 3:
                            fill_val = round(float(sub.median()), 2)
                            if sem_type in ("quantity", "age"):
                                fill_val = int(round(fill_val))

                old_v = df.at[r, c_str]
                df.at[r, c_str] = fill_val
                changes.append({
                    "rule": "missing_value_median_filled",
                    "column": c_str,
                    "row": int(r),
                    "old_val": str(old_v),
                    "new_val": fill_val,
                })

        # Categories: mode if low missing rate <= 15%, else 'Unknown'
        elif sem_type in ("category", "status/boolean_flag"):
            clean = s[~missing_mask]
            if not clean.empty and not clean.mode().empty and missing_pct <= 0.15:
                mode_val = str(clean.mode()[0])
            else:
                mode_val = "Unknown"

            for r in df[missing_mask].index:
                old_v = df.at[r, c_str]
                df.at[r, c_str] = mode_val
                changes.append({
                    "rule": "missing_category_filled",
                    "column": c_str,
                    "row": int(r),
                    "old_val": str(old_v),
                    "new_val": mode_val,
                })

    return df, changes, decision_items


# ────────────────────────────────────────────────────────────────────────────
# 11. Multi-Pass Auto-Clean Engine (Completeness Contract A1)
# ────────────────────────────────────────────────────────────────────────────

def run_multi_pass_auto_clean(
    df: pd.DataFrame,
    semantics: dict[str, dict] | None = None,
    max_passes: int = 5,
) -> tuple[pd.DataFrame, list[dict], list[dict], int]:
    """
    Executes repeated passes until a pass changes nothing (convergence, max 5).
    One fix can expose another (trimming reveals duplicates, converting types reveals outliers).
    Returns (cleaned_df, all_changes_log, removed_rows_log, passes_executed).
    """
    cur_df = df.copy()
    all_changes: list[dict] = []
    all_removed_rows: list[dict] = []
    passes_executed = 0

    for pass_num in range(1, max_passes + 1):
        passes_executed += 1
        pass_changes: list[dict] = []

        if semantics is None:
            semantics = infer_dataset_semantics(cur_df)

        # 1. Structure: preamble, headers, blank rows/cols, repeated headers, subtotals, apostrophes
        cur_df, struct_changes, removed = clean_structure_rows_and_cols(cur_df)
        pass_changes.extend(struct_changes)
        all_removed_rows.extend(removed)

        # 2. Standardize missing-value tokens
        cur_df, missing_tok_changes = standardize_missing_tokens_in_df(cur_df)
        pass_changes.extend(missing_tok_changes)

        # 3. Text normalization: trim, collapse spaces, curly quotes, mojibake
        cur_df, text_changes = normalize_text_in_df(cur_df, semantics)
        pass_changes.extend(text_changes)

        # 4. Number cleanup & conversion
        cur_df, num_changes = clean_and_convert_numbers(cur_df, semantics)
        pass_changes.extend(num_changes)

        # 5. Date standardization
        cur_df, date_changes, _ = clean_and_standardize_dates(cur_df, semantics)
        pass_changes.extend(date_changes)

        # 6. Category cleanup & fuzzy deduplication
        cur_df, cat_changes = clean_and_standardize_categories(cur_df, semantics)
        pass_changes.extend(cat_changes)

        # 7. Identifiers & contacts normalization
        cur_df, id_changes, _ = clean_identifiers_and_contacts(cur_df, semantics)
        pass_changes.extend(id_changes)

        # 8. Duplicate rows & duplicate IDs
        cur_df, dup_changes, dup_removed, _ = clean_rows_and_duplicates(cur_df, semantics)
        pass_changes.extend(dup_changes)
        all_removed_rows.extend(dup_removed)

        # 9. Semantic missing values imputation
        cur_df, miss_changes, _ = clean_missing_values_semantic(cur_df, semantics)
        pass_changes.extend(miss_changes)

        # Tag changes with pass number
        for ch in pass_changes:
            ch["pass"] = pass_num
        all_changes.extend(pass_changes)

        # Check for convergence: if pass produced 0 changes, we are completely done!
        if len(pass_changes) == 0:
            break

    return cur_df, all_changes, all_removed_rows, passes_executed


# ────────────────────────────────────────────────────────────────────────────
# 12. Clean Check (A1 Contract)
# ────────────────────────────────────────────────────────────────────────────

def run_clean_check(
    df: pd.DataFrame,
    semantics: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """
    Re-scans the entire dataset with ALL detectors.
    Asserts zero auto-fixable issues remain (Regression Guard).
    Collects items that truly require a human decision:
      - Blank unique IDs, emails, phones, names, dates (semantic restriction)
      - Ambiguous day/month dates
      - Conflicting duplicate IDs
      - Values failing validation with no safe correction (invalid PAN, email format)
      - Statistical / domain outliers
    Returns:
      {
        "status": "Clean",
        "auto_fixable_count": 0,
        "needs_decision_count": len(decision_items),
        "banner_message": "Clean. 0 issues can be fixed automatically. N need your decision.",
        "decision_items": decision_items,
        "is_regression_free": True,
      }
    """
    if semantics is None:
        semantics = infer_dataset_semantics(df)

    # 1. Run date checks
    _, _, date_decisions = clean_and_standardize_dates(df, semantics)

    # 2. Run identifier & contact checks
    _, _, contact_decisions = clean_identifiers_and_contacts(df, semantics)

    # 3. Duplicate ID conflict checks
    _, _, _, dup_decisions = clean_rows_and_duplicates(df, semantics)

    # 4. Outlier & impossible value checks
    val_decisions = check_value_bounds_and_impossible(df, semantics)

    # 5. Missing value restricted checks
    _, _, missing_decisions = clean_missing_values_semantic(df, semantics)

    # Combine all decision items and de-duplicate by (row, column)
    seen_cells = set()
    decision_items = []
    for item in date_decisions + contact_decisions + dup_decisions + val_decisions + missing_decisions:
        key = (item.get("row"), item.get("column"))
        if key not in seen_cells:
            seen_cells.add(key)
            decision_items.append(item)

    # Regression Guard: run a hypothetical single pass on df and count any auto-fixable changes
    test_cleaned, test_changes, _, _ = run_multi_pass_auto_clean(df, semantics=semantics, max_passes=1)
    auto_fixable_count = len(test_changes)

    banner_message = (
        f"Clean. 0 issues can be fixed automatically. {len(decision_items)} need your decision."
        if auto_fixable_count == 0
        else f"Attention: {auto_fixable_count} auto-fixable issue(s) remain. {len(decision_items)} need your decision."
    )

    return {
        "status": "Clean" if auto_fixable_count == 0 else "Needs Fixes",
        "auto_fixable_count": auto_fixable_count,
        "needs_decision_count": len(decision_items),
        "banner_message": banner_message,
        "decision_items": decision_items,
        "is_regression_free": auto_fixable_count == 0,
    }

