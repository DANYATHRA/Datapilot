"""Cleaning steps are plain dicts {op, params}. They are stored in Mongo as the audit trail,
so any dataset version can be reproduced by replaying its steps."""
import hashlib
import hmac
import re
import warnings

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from ..config import settings
from .profiling import CURRENCY_CHARS, date_like_ratio, numeric_like_ratio, pii_columns
from .util import text_cols


class CleaningError(ValueError):
    pass


def _cols(df, params, key="columns", default_all_text=False):
    cols = params.get(key) or ([params["column"]] if params.get("column") else None)
    if not cols:
        if default_all_text:
            return text_cols(df)
        raise CleaningError(f"'{key}' is required")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise CleaningError(f"Unknown column(s): {missing}")
    return cols


def drop_duplicates(df, p):
    subset = _cols(df, p) if p.get("columns") or p.get("column") else None
    return df.drop_duplicates(subset=subset).reset_index(drop=True)


def drop_nulls(df, p):
    cols = _cols(df, p) if p.get("columns") or p.get("column") else None
    return df.dropna(subset=cols).reset_index(drop=True)


def fill_nulls(df, p):
    for c in _cols(df, p):
        s, how = df[c], p.get("strategy", "value")
        if how in ("mean", "median"):
            if not pd.api.types.is_numeric_dtype(s):
                raise CleaningError(f"{how} needs a numeric column ({c})")
            df[c] = s.fillna(s.mean() if how == "mean" else s.median())
        elif how == "mode":
            m = s.mode(dropna=True)
            df[c] = s.fillna(m.iloc[0]) if len(m) else s
        elif how == "ffill":
            df[c] = s.ffill()
        elif how == "value":
            val = p.get("value")
            if pd.api.types.is_numeric_dtype(s):
                val = pd.to_numeric(val, errors="coerce")
            df[c] = s.fillna(val)
        else:
            raise CleaningError(f"Unknown strategy {how}")
    return df


def cast(df, p):
    t = p.get("dtype")
    for c in _cols(df, p):
        if t == "int":
            df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
        elif t == "float":
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        elif t == "str":
            df[c] = df[c].astype("string").astype(object).where(df[c].notna(), None)
        elif t == "datetime":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
        elif t == "bool":
            df[c] = df[c].map(lambda x: str(x).strip().lower() in ("1", "true", "yes", "y") if pd.notna(x) else None)
        else:
            raise CleaningError("dtype must be int|float|str|datetime|bool")
    return df


def strip_currency(df, p):
    for c in _cols(df, p):
        cleaned = df[c].astype("string").str.replace(CURRENCY_CHARS, "", regex=True)
        cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (123) -> -123
        df[c] = pd.to_numeric(cleaned, errors="coerce").astype(float)
    return df


def trim(df, p):
    for c in _cols(df, p, default_all_text=True):
        df[c] = df[c].astype("string").str.strip().astype(object).where(df[c].notna(), None)
    return df


def change_case(df, p):
    case = p.get("case", "lower")
    for c in _cols(df, p):
        s = df[c].astype("string")
        s = {"lower": s.str.lower, "upper": s.str.upper, "title": s.str.title}[case]()
        df[c] = s.astype(object).where(df[c].notna(), None)
    return df


def rename(df, p):
    m = p.get("mapping") or {}
    bad = [k for k in m if k not in df.columns]
    if bad:
        raise CleaningError(f"Unknown column(s): {bad}")
    return df.rename(columns=m)


def drop_columns(df, p):
    return df.drop(columns=_cols(df, p))


def replace_values(df, p):
    c = _cols(df, p)[0]
    return df.assign(**{c: df[c].replace(p.get("mapping") or {})})


def filter_rows(df, p):
    c, op, val = _cols(df, p)[0], p.get("operator", "=="), p.get("value")
    s = df[c]
    if op == "isnull":
        mask = s.isna()
    elif op == "notnull":
        mask = s.notna()
    elif op == "contains":
        mask = s.astype("string").str.contains(str(val), case=False, na=False, regex=False)
    else:
        if pd.api.types.is_numeric_dtype(s):
            val = pd.to_numeric(val, errors="coerce")
        elif pd.api.types.is_datetime64_any_dtype(s):
            val = pd.to_datetime(val)
        mask = {"==": s == val, "!=": s != val, ">": s > val, ">=": s >= val,
                "<": s < val, "<=": s <= val}.get(op)
        if mask is None:
            raise CleaningError(f"Unknown operator {op}")
    return df[mask.fillna(False)].reset_index(drop=True)


def clip_outliers(df, p):
    method, k = p.get("method", "iqr"), float(p.get("factor", 1.5))
    for c in _cols(df, p):
        s = df[c]
        if not pd.api.types.is_numeric_dtype(s):
            raise CleaningError(f"{c} is not numeric")
        if method == "zscore":
            m, sd = s.mean(), s.std()
            lo, hi = m - 3 * sd, m + 3 * sd
        else:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        df[c] = s.clip(lo, hi)
    return df


def mask_pii(df, p):
    mode = p.get("mode", "hash")
    key = settings.JWT_SECRET.encode()

    def one(x):
        if pd.isna(x):
            return x
        x = str(x)
        if mode == "hash":  # keyed HMAC so low-entropy values (phones) can't be brute-forced without the key
            return hmac.new(key, x.encode(), hashlib.sha256).hexdigest()[:16]
        if "@" in x:
            u, d = x.split("@", 1)
            return u[:1] + "***@" + d
        return "*" * max(len(x) - 2, 0) + x[-2:]

    for c in _cols(df, p):
        df[c] = df[c].map(one).astype(object)
    return df


OPS = {
    "drop_duplicates": drop_duplicates, "drop_nulls": drop_nulls, "fill_nulls": fill_nulls,
    "cast": cast, "strip_currency": strip_currency, "trim": trim, "change_case": change_case,
    "rename": rename, "drop_columns": drop_columns, "replace_values": replace_values,
    "filter": filter_rows, "clip_outliers": clip_outliers, "mask_pii": mask_pii,
}


def apply_step(df: pd.DataFrame, step: dict) -> pd.DataFrame:
    from . import cleaning_engine
    op = step.get("op")
    if op in cleaning_engine.CLEANING_DISPATCH:
        cleaned_df, _ = cleaning_engine.execute_step(df, step)
        return cleaned_df
    fn = OPS.get(op)
    if not fn:
        all_ops = sorted(set(list(OPS.keys()) + list(cleaning_engine.CLEANING_DISPATCH.keys())))
        raise CleaningError(f"Unknown op '{op}'. Available: {all_ops}")
    return fn(df.copy(), step.get("params") or {})


def suggest(df: pd.DataFrame) -> list[dict]:
    """Rule-based smart suggestions, each one click-applicable."""
    out = []

    def add(title, reason, op, params):
        out.append({"id": f"s{len(out) + 1}", "title": title, "reason": reason,
                    "step": {"op": op, "params": params}})

    dup = int(df.duplicated().sum())
    if dup:
        add(f"Drop {dup} duplicate rows", "Exact duplicate rows found.", "drop_duplicates", {})
    for c in text_cols(df):
        s = df[c].dropna().astype(str)
        if s.empty:
            continue
        if numeric_like_ratio(df[c]) > 0.8 and s.str.contains(r"[^\d.\-\s]").any():
            add(f"Convert '{c}' to a number", "Values look numeric but contain currency symbols, commas or text.",
                "strip_currency", {"columns": [c]})
        elif date_like_ratio(df[c]) > 0.8:
            add(f"Parse '{c}' as dates", "Values parse as dates (mixed formats are handled).",
                "cast", {"columns": [c], "dtype": "datetime"})
        elif (s != s.str.strip()).any():
            add(f"Trim whitespace in '{c}'", "Leading/trailing spaces will break grouping and joins.",
                "trim", {"columns": [c]})
        if 1 < s.nunique() <= 300 and numeric_like_ratio(df[c]) < 0.5:
            vc = s.str.strip().value_counts()
            vals = list(vc.index)
            mapping = {}
            for i, a in enumerate(vals):
                if a in mapping:
                    continue
                for b in vals[i + 1:]:
                    if b not in mapping and (a.lower() == b.lower() or fuzz.ratio(a.lower(), b.lower()) >= 85):
                        mapping[b] = a  # map the rarer spelling to the most common one
            if mapping:
                add(f"Standardise {len(mapping)} near-duplicate value(s) in '{c}'",
                    "Similar spellings: " + ", ".join(f"'{k}'→'{v}'" for k, v in list(mapping.items())[:4]),
                    "replace_values", {"column": c, "mapping": mapping})
    from .column_semantics import infer_dataset_semantics
    from .missing_policy import POLICY_MATRIX
    semantics = infer_dataset_semantics(df)
    for c in df.columns:
        nn = int(df[c].isna().sum())
        if nn and nn / len(df) < 0.5:
            sem_type = semantics.get(c, {}).get("semantic_type", "other_text")
            policy = POLICY_MATRIX.get(sem_type, {})
            # Never suggest imputation for identifiers, email, phone, date, rating, marks, etc.
            if not policy.get("can_impute", False):
                continue
            if sem_type in ("money_amount", "quantity", "other_numeric", "age"):
                add(f"Fill {nn} missing in '{c}' with median", f"Robust median imputation for {sem_type}.",
                    "fill_nulls", {"columns": [c], "strategy": "median"})
            elif sem_type == "category" and (nn / len(df)) < 0.05 and df[c].nunique() <= 20:
                add(f"Fill {nn} missing in '{c}' with most frequent value", "Mode imputation for categorical data.",
                    "fill_nulls", {"columns": [c], "strategy": "mode"})
    for c, kind in pii_columns(df).items():
        add(f"Mask PII column '{c}' ({kind})", "Personal data detected; hash it before sharing or analysis.",
            "mask_pii", {"columns": [c], "mode": "hash"})
    return out
