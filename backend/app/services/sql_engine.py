"""DuckDB SQL over a user's datasets. Read-only, single SELECT statement, timeout, row cap,
and external file/network access disabled after tables are registered."""
import re
import threading

import duckdb

from ..config import settings
from ..db import datasets
from .datasets import load_df
from .profiling import pii_columns
from .util import qid, text_cols, to_json_table


class SQLError(Exception):
    pass


def connect(owner: str, sql_hint: str | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for d in datasets.find({"owner": owner}):
        if sql_hint is None or re.search(rf"\b{re.escape(d['table'])}\b", sql_hint, re.I):
            con.register(d["table"], load_df(d))
    con.execute("SET memory_limit='1GB'")
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    return con


def validate(con, sql: str) -> str:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise SQLError("Empty query")
    try:
        stmts = con.extract_statements(sql)
    except Exception as e:
        raise SQLError(str(e))
    if len(stmts) != 1:
        raise SQLError("Only a single statement is allowed")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise SQLError("Only read-only SELECT queries are allowed")
    return sql


def run_df(owner: str, sql: str, max_rows: int | None = None, timeout: float | None = None):
    max_rows = max_rows or settings.SQL_MAX_ROWS
    timeout = timeout or settings.SQL_TIMEOUT_S
    con = connect(owner, sql)
    timer = None
    try:
        sql = validate(con, sql)
        timer = threading.Timer(timeout, con.interrupt)
        timer.start()
        df = con.execute(f"SELECT * FROM ({sql}) AS _q LIMIT {int(max_rows) + 1}").fetchdf()
    except duckdb.InterruptException:
        raise SQLError(f"Query exceeded the {timeout:g}s time limit")
    except SQLError:
        raise
    except Exception as e:
        raise SQLError(str(e))
    finally:
        if timer:
            timer.cancel()
        con.close()
    truncated = len(df) > max_rows
    return df.head(max_rows), truncated


def run(owner: str, sql: str, max_rows: int | None = None) -> dict:
    df, truncated = run_df(owner, sql, max_rows)
    t = to_json_table(df)
    return {**t, "row_count": len(df), "truncated": truncated}


def explain(owner: str, sql: str) -> str:
    con = connect(owner, sql)
    try:
        sql = validate(con, sql)
        rows = con.execute(f"EXPLAIN {sql}").fetchall()
        return "\n".join(str(r[1]) for r in rows)
    except SQLError:
        raise
    except Exception as e:
        raise SQLError(str(e))
    finally:
        con.close()


def schema_context(owner: str, share_values: bool | None = None) -> str:
    """Compact schema text for the LLM: columns, types, numeric ranges and (optionally) the
    distinct values of low-cardinality non-PII text columns. Never full rows."""
    share_values = settings.LLM_SHARE_VALUES if share_values is None else share_values
    parts = []
    for d in datasets.find({"owner": owner}):
        df = load_df(d)
        pii = pii_columns(df)
        lines = [f"TABLE {d['table']} ({len(df)} rows)"]
        tcols = set(text_cols(df))
        for c in df.columns:
            desc = f"  {qid(c)} {df[c].dtype}"
            if c in pii:
                desc += " [PII - values hidden]"
            elif c in tcols and share_values and df[c].nunique() <= 12:
                desc += " values=" + str(sorted(df[c].dropna().astype(str).unique())[:12])
            elif df[c].dtype.kind in "iuf" and df[c].notna().any():
                desc += f" range=[{df[c].min()}, {df[c].max()}]"
            elif df[c].dtype.kind == "M" and df[c].notna().any():
                desc += f" range=[{df[c].min()}, {df[c].max()}]"
            lines.append(desc)
        parts.append("\n".join(lines))
    return "\n\n".join(parts) or "(no tables)"
