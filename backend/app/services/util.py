import json

import pandas as pd


def text_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c])]


def to_json_table(df: pd.DataFrame, n: int | None = None) -> dict:
    """JSON-safe {columns, rows} (NaN -> null, timestamps -> ISO)."""
    d = df if n is None else df.head(n)
    s = json.loads(d.to_json(orient="split", date_format="iso"))
    return {"columns": s["columns"], "rows": s["data"]}


def qid(name: str) -> str:
    """Quote a SQL identifier."""
    return '"' + str(name).replace('"', '""') + '"'
