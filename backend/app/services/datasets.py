import datetime as dt
import re
import uuid

import pandas as pd
from fastapi import HTTPException

from ..config import settings
from ..db import datasets
from .util import text_cols


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def table_name(name: str) -> str:
    base = re.sub(r"\.[^.]+$", "", name)
    t = re.sub(r"\W+", "_", base).strip("_").lower() or "dataset"
    return "t_" + t if t[0].isdigit() else t


def unique_table(owner: str, name: str) -> str:
    existing = {d["table"] for d in datasets.find({"owner": owner})}
    t = table_name(name)
    cand, i = t, 2
    while cand in existing:
        cand, i = f"{t}_{i}", i + 1
    return cand


def vpath(owner: str, ds_id: str, v: int):
    p = settings.DATA_DIR / owner / ds_id
    target = p / f"v{v}.parquet"
    if not target.exists():
        from pathlib import Path
        # Check project root data dir
        alt = Path(__file__).resolve().parents[3] / "data" / owner / ds_id / f"v{v}.parquet"
        if alt.exists():
            return alt
        alt_backend = Path(__file__).resolve().parents[2] / "data" / owner / ds_id / f"v{v}.parquet"
        if alt_backend.exists():
            return alt_backend
    p.mkdir(parents=True, exist_ok=True)
    return target


def sanitize(df: pd.DataFrame) -> pd.DataFrame:
    """Make a frame Parquet-safe: unique string column names, no mixed-type object columns."""
    df = df.copy()
    seen: dict[str, int] = {}
    cols = []
    for c in df.columns:
        c = str(c).strip() or "column"
        n = seen.get(c, 0)
        seen[c] = n + 1
        cols.append(c if n == 0 else f"{c}_{n}")
    df.columns = cols
    for c in text_cols(df):
        if pd.api.types.is_object_dtype(df[c]):
            df[c] = df[c].map(lambda x: x if (x is None or isinstance(x, str) or pd.isna(x)) else str(x))
    return df


def create_dataset(owner: str, filename: str, df: pd.DataFrame) -> dict:
    df = sanitize(df)
    ds_id = uuid.uuid4().hex[:12]
    doc = {
        "_id": ds_id, "owner": owner, "name": filename,
        "table": unique_table(owner, filename),
        "current_version": 1, "created": _now(),
        "versions": [{"v": 1, "rows": len(df), "cols": df.shape[1], "parent": None,
                      "step": {"op": "upload", "params": {"filename": filename}}, "created": _now()}],
    }
    df.to_parquet(vpath(owner, ds_id, 1), index=False)
    datasets.insert_one(doc)
    return doc


def get_dataset(owner: str, ds_id: str) -> dict:
    doc = datasets.find_one({"_id": ds_id, "owner": owner})
    if not doc:
        raise HTTPException(404, "Dataset not found")
    return doc


def load_df(doc: dict, v: int | None = None) -> pd.DataFrame:
    return pd.read_parquet(vpath(doc["owner"], doc["_id"], v or doc["current_version"]))


def add_version(doc: dict, df: pd.DataFrame, step: dict) -> int:
    """Every change creates a new immutable version (audit trail + time travel)."""
    df = sanitize(df)
    v = max(x["v"] for x in doc["versions"]) + 1
    df.to_parquet(vpath(doc["owner"], doc["_id"], v), index=False)
    prev = next(x for x in doc["versions"] if x["v"] == doc["current_version"])
    entry = {"v": v, "rows": len(df), "cols": df.shape[1], "parent": doc["current_version"],
             "rows_before": prev["rows"], "step": step, "created": _now()}
    datasets.update_one({"_id": doc["_id"]},
                        {"$push": {"versions": entry}, "$set": {"current_version": v}})
    return v


def read_upload(filename: str, raw: bytes, sheet_name: str | None = None) -> pd.DataFrame:
    from .parser import parse_uploaded_file
    df, _ = parse_uploaded_file(filename, raw, sheet_name=sheet_name)
    return df
