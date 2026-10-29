import re
import warnings

import numpy as np
import pandas as pd

from .util import text_cols

PII_PATTERNS = {
    "email": re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"),
    "phone_in": re.compile(r"^(\+91[\-\s]?)?[6-9]\d{9}$"),
    "aadhaar": re.compile(r"^\d{4}\s?\d{4}\s?\d{4}$"),
    "pan": re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$"),
}
CURRENCY_CHARS = re.compile(r"[₹$€£,\s]")


def detect_pii(s: pd.Series) -> str | None:
    vals = s.dropna().astype(str).str.strip()
    vals = vals[vals != ""].head(500)
    if len(vals) < 3:
        return None
    for name, rx in PII_PATTERNS.items():
        if vals.map(lambda x: bool(rx.match(x))).mean() >= 0.6:
            return name
    return None


def pii_columns(df: pd.DataFrame) -> dict[str, str]:
    out = {}
    for c in text_cols(df) + [c for c in df.columns if pd.api.types.is_integer_dtype(df[c])]:
        kind = detect_pii(df[c])
        if kind in ("email", "pan") or (kind in ("phone_in", "aadhaar") and not pd.api.types.is_float_dtype(df[c])):
            out[c] = kind
    return out


def _iqr_bounds(s: pd.Series):
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def numeric_like_ratio(s: pd.Series) -> float:
    vals = s.dropna().astype(str)
    if vals.empty:
        return 0.0
    cleaned = vals.map(lambda x: CURRENCY_CHARS.sub("", x))
    return float(pd.to_numeric(cleaned, errors="coerce").notna().mean())


def date_like_ratio(s: pd.Series) -> float:
    vals = s.dropna().astype(str).head(300)
    if vals.empty or vals.str.fullmatch(r"-?\d+(\.\d+)?").mean() > 0.5:
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(pd.to_datetime(vals, errors="coerce", format="mixed").notna().mean())


def format_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{round(b / 1024, 1)} KB"
    else:
        return f"{round(b / (1024 * 1024), 2)} MB"


def find_inconsistent_categories(series: pd.Series, max_unique: int = 250) -> list[dict]:
    """Identify candidate near-duplicate or differently cased category values."""
    from rapidfuzz import fuzz

    non_null = series.dropna().astype(str).str.strip()
    non_null = non_null[non_null != ""]
    unique_vals = non_null.unique()
    if len(unique_vals) <= 1 or len(unique_vals) > max_unique:
        return []

    vc = non_null.value_counts().to_dict()
    pairs = []
    seen = set()
    vals = list(unique_vals)

    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            key = tuple(sorted([a, b]))
            if key in seen:
                continue
            # Case difference
            if a.lower() == b.lower() and a != b:
                seen.add(key)
                pairs.append({"a": a, "b": b, "similarity": 100, "reason": "case_difference", "count_a": vc.get(a, 0), "count_b": vc.get(b, 0)})
            elif len(a) >= 3 and len(b) >= 3:
                sim = fuzz.ratio(a.lower(), b.lower())
                if sim >= 85:
                    seen.add(key)
                    pairs.append({"a": a, "b": b, "similarity": round(sim, 1), "reason": "spelling_variation", "count_a": vc.get(a, 0), "count_b": vc.get(b, 0)})
            if len(pairs) >= 10:
                break
        if len(pairs) >= 10:
            break
    return pairs


def profile(df: pd.DataFrame) -> dict:
    n = len(df)
    n_cols = df.shape[1]
    pii = pii_columns(df)
    cols = []
    mixed_or_dirty = 0
    outlier_cells = 0
    constant_cols_count = 0

    from .column_semantics import infer_dataset_semantics
    semantics = infer_dataset_semantics(df)

    for c in df.columns:
        s = df[c]
        null_count = int(s.isna().sum())
        null_pct = round(float(null_count / n * 100), 2) if n else 0.0
        uniq = int(s.nunique(dropna=True))
        is_const = bool(uniq == 1 and s.notna().any())
        is_empty = bool(null_count == n)
        if is_const:
            constant_cols_count += 1

        sem_info = semantics.get(c, {})
        info = {
            "name": c,
            "dtype": str(s.dtype),
            "nulls": null_count,
            "null_pct": null_pct,
            "unique": uniq,
            "unique_pct": round(float(uniq / n * 100), 2) if n else 0.0,
            "is_constant": is_const,
            "is_empty": is_empty,
            "semantic_type": sem_info.get("semantic_type", "other_text"),
            "semantic_confidence": sem_info.get("confidence", 0.5),
            "semantic_evidence": sem_info.get("evidence", ""),
            "needs_confirmation": sem_info.get("needs_confirmation", False),
        }

        if pd.api.types.is_bool_dtype(s):
            info["kind"] = "boolean"
            vc = s.value_counts(dropna=True).to_dict()
            info["top_values"] = [{"value": str(k), "count": int(v)} for k, v in vc.items()]
        elif pd.api.types.is_numeric_dtype(s):
            info["kind"] = "numeric"
            v = s.dropna().astype(float)
            if len(v):
                m, sd = float(v.mean()), float(v.std()) if len(v) > 1 else 0.0
                info.update(
                    min=float(v.min()), max=float(v.max()), mean=round(m, 4),
                    median=float(v.median()), std=round(sd, 4),
                    negative_count=int((v < 0).sum()),
                    zero_count=int((v == 0).sum())
                )
                if len(v) >= 8:
                    lo, hi = _iqr_bounds(v)
                    o_iqr = int(((v < lo) | (v > hi)).sum())
                    info["outliers"] = o_iqr
                    info["iqr_bounds"] = [round(lo, 2), round(hi, 2)]
                    outlier_cells += o_iqr

                    # Z-score candidate outliers
                    if sd > 0:
                        z_scores = (v - m).abs() / sd
                        info["zscore_outliers"] = int((z_scores > 3.0).sum())
                    else:
                        info["zscore_outliers"] = 0

                hist, edges = np.histogram(v, bins=min(20, max(1, info["unique"])))
                info["hist"] = {"counts": hist.tolist(), "edges": [float(e) for e in edges]}
        elif pd.api.types.is_datetime64_any_dtype(s):
            info["kind"] = "datetime"
            if s.notna().any():
                info.update(min=str(s.min()), max=str(s.max()))
        else:
            info["kind"] = "text"
            text_s = s.dropna().astype(str)
            top = text_s.value_counts().head(5)
            info["top_values"] = [{"value": k, "count": int(v)} for k, v in top.items()]

            # Whitespace inspection
            ws_count = int(text_s.map(lambda x: x != x.strip()).sum())
            if ws_count:
                info["whitespace_issues"] = ws_count
                mixed_or_dirty += 1

            # Candidate spelling variations
            spelling_candidates = find_inconsistent_categories(s)
            if spelling_candidates:
                info["inconsistent_categories"] = spelling_candidates

            # Check if looks like numeric or date
            num_ratio = numeric_like_ratio(s)
            d_ratio = date_like_ratio(s)
            if num_ratio > 0.8:
                mixed_or_dirty += 1
                info["looks_like"] = "numeric"
            elif d_ratio > 0.8:
                mixed_or_dirty += 1
                info["looks_like"] = "date"
                # Check unparseable count
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    unparseable = int(pd.to_datetime(text_s, errors="coerce", format="mixed").isna().sum())
                    if unparseable:
                        info["unparseable_dates"] = unparseable

        if c in pii:
            info["pii"] = pii[c]
        cols.append(info)

    total_cells = max(n * max(n_cols, 1), 1)
    missing_cells = int(df.isna().sum().sum())
    completeness = 1 - missing_cells / total_cells
    dup_rows = int(df.duplicated().sum()) if n else 0
    uniqueness = 1 - dup_rows / n if n else 1.0
    validity = 1 - outlier_cells / total_cells
    consistency = 1 - mixed_or_dirty / max(n_cols, 1)
    score = 100 * (0.35 * completeness + 0.25 * uniqueness + 0.2 * validity + 0.2 * consistency)

    empty_rows = int(df.isna().all(axis=1).sum()) if n else 0
    empty_cols = int(df.isna().all(axis=0).sum()) if n_cols else 0

    try:
        mem_bytes = int(df.memory_usage(deep=True).sum())
    except Exception:
        mem_bytes = 0

    return {
        "rows": n,
        "cols": n_cols,
        "total_cells": total_cells,
        "missing_cells": missing_cells,
        "missing_pct": round(missing_cells / total_cells * 100, 2),
        "duplicate_rows": dup_rows,
        "duplicate_pct": round(dup_rows / n * 100, 2) if n else 0.0,
        "empty_rows": empty_rows,
        "empty_cols": empty_cols,
        "constant_cols": constant_cols_count,
        "mixed_or_dirty_cols": mixed_or_dirty,
        "memory_bytes": mem_bytes,
        "memory_formatted": format_bytes(mem_bytes),
        "quality": {
            "score": round(score, 1),
            "completeness": round(completeness * 100, 1),
            "uniqueness": round(uniqueness * 100, 1),
            "validity": round(validity * 100, 1),
            "consistency": round(consistency * 100, 1),
        },
        "pii_columns": pii,
        "has_rating_scale": any(c.get("semantic_type") == "rating_scale" for c in cols),
        "columns": cols,
    }
