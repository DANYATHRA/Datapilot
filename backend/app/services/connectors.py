"""Multi-source data connector service.

Supports: file upload (CSV/Excel/JSON/Parquet), SQLAlchemy databases
(PostgreSQL, MySQL, SQL Server, SQLite, ODBC/DSN), REST API (GET with
pagination), and URL import (public CSV).

Security:
  - Credentials encrypted at rest via Fernet (see encryption module)
  - SSRF protection blocks private-network and metadata addresses
  - Read-only enforcement: only SELECT statements allowed
  - Configurable query timeout and row cap
  - Per-user isolation via owner field
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd

from ..config import settings
from ..db import db
from .encryption import decrypt, encrypt

# ── MongoDB collection ─────────────────────────────────────────────
connections = db["connections"]
sources = db["sources"]
pull_history = db["pull_history"]

# ── Constants ──────────────────────────────────────────────────────
SUPPORTED_DB_TYPES = {"postgresql", "mysql", "mssql", "sqlite", "odbc"}
CONNECTOR_ROW_CAP = int(os.getenv("CONNECTOR_ROW_CAP", "500000"))
CONNECTOR_TIMEOUT_S = float(os.getenv("CONNECTOR_TIMEOUT_S", "60"))
HOST_ALLOWLIST_RAW = os.getenv("CONNECTOR_HOST_ALLOWLIST", "")
HOST_ALLOWLIST = {h.strip().lower() for h in HOST_ALLOWLIST_RAW.split(",") if h.strip()} if HOST_ALLOWLIST_RAW else None

# Private / metadata IP ranges to block (SSRF protection)
_BLOCKED_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local + cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


# ── SSRF protection ───────────────────────────────────────────────
def _is_private_ip(host: str) -> bool:
    """Return True if host resolves to a private/blocked IP."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in resolved:
                addr = ipaddress.ip_address(sockaddr[0])
                if any(addr in net for net in _BLOCKED_NETS):
                    return True
            return False
        except socket.gaierror:
            return True  # unresolvable → block
    return any(addr in net for net in _BLOCKED_NETS)


def _validate_url_safe(url: str) -> None:
    """Raise ValueError if URL targets a private/metadata address."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL has no host")
    if HOST_ALLOWLIST is not None and host.lower() not in HOST_ALLOWLIST:
        raise ValueError(f"Host '{host}' not in allowlist")
    if _is_private_ip(host):
        raise ValueError(f"Blocked: '{host}' resolves to a private/metadata address")


# ── SQL safety ────────────────────────────────────────────────────
_WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|MERGE|REPLACE)\b",
    re.IGNORECASE,
)


def _assert_select_only(sql: str) -> None:
    """Raise if sql contains write/DDL keywords."""
    stripped = sql.strip().rstrip(";").strip()
    if _WRITE_KEYWORDS.search(stripped):
        raise ValueError("Only SELECT queries are allowed on external connections")


# ── ERP export quirk detection ────────────────────────────────────
def detect_erp_quirks(df: pd.DataFrame) -> dict:
    """Detect common ERP-style export problems."""
    quirks = {}
    if df.empty:
        return quirks

    # Title rows: first 1-3 rows where most columns are NaN
    title_rows = []
    for i in range(min(5, len(df))):
        null_pct = df.iloc[i].isna().mean()
        if null_pct > 0.6:
            title_rows.append(i)
        else:
            break
    if title_rows:
        quirks["title_rows"] = title_rows

    # Subtotal rows: rows where a text column contains 'total', 'subtotal', 'sum'
    total_pattern = re.compile(r"\b(sub\s*total|total|sum|grand\s*total)\b", re.IGNORECASE)
    subtotal_indices = []
    for col in df.select_dtypes(include="object").columns[:5]:
        matches = df[col].dropna().astype(str).str.contains(total_pattern, na=False)
        subtotal_indices.extend(matches[matches].index.tolist())
    subtotal_indices = sorted(set(subtotal_indices))
    if subtotal_indices:
        quirks["subtotal_rows"] = subtotal_indices[:20]

    # Text-formatted numbers: object columns where > 80% parse as numeric
    text_numbers = []
    for col in df.select_dtypes(include="object").columns:
        vals = df[col].dropna().astype(str).str.replace(",", "", regex=False).str.strip()
        if len(vals) > 0:
            numeric_ratio = pd.to_numeric(vals, errors="coerce").notna().mean()
            if numeric_ratio > 0.8:
                text_numbers.append(col)
    if text_numbers:
        quirks["text_formatted_numbers"] = text_numbers

    # Trailing totals: last row looks like a total
    if len(df) > 2:
        last = df.iloc[-1]
        for col in df.select_dtypes(include="object").columns[:5]:
            val = str(last.get(col, ""))
            if total_pattern.search(val):
                quirks["trailing_total_row"] = len(df) - 1
                break

    return quirks


# ── Connection CRUD ───────────────────────────────────────────────
def _sanitize_conn(doc: dict) -> dict:
    """Strip encrypted credentials before returning to the browser."""
    safe = {k: v for k, v in doc.items() if k not in ("password_enc", "api_key_enc", "headers_enc")}
    safe["id"] = str(doc["_id"])
    safe["has_password"] = bool(doc.get("password_enc"))
    return safe


def create_connection(owner: str, data: dict) -> dict:
    conn_type = data["type"]
    doc = {
        "_id": uuid.uuid4().hex[:12],
        "owner": owner,
        "type": conn_type,
        "name": data["name"],
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": datetime.now(timezone.utc).isoformat(),
    }

    if conn_type in SUPPORTED_DB_TYPES:
        doc["host"] = data.get("host", "")
        doc["port"] = int(data.get("port", 0))
        doc["database"] = data.get("database", "")
        doc["username"] = data.get("username", "")
        if data.get("password"):
            doc["password_enc"] = encrypt(data["password"])
        doc["schema_name"] = data.get("schema_name", "")
        if conn_type == "sqlite":
            doc["file_path"] = data.get("file_path", "")
        if conn_type == "odbc":
            doc["dsn"] = data.get("dsn", "")
            doc["connection_string"] = data.get("connection_string", "")
    elif conn_type == "rest_api":
        doc["base_url"] = data.get("base_url", "")
        doc["json_path"] = data.get("json_path", "data")
        doc["pagination_type"] = data.get("pagination_type", "none")
        doc["page_param"] = data.get("page_param", "page")
        doc["page_size_param"] = data.get("page_size_param", "per_page")
        doc["page_size"] = int(data.get("page_size", 100))
        doc["max_pages"] = int(data.get("max_pages", 10))
        if data.get("headers"):
            doc["headers_enc"] = encrypt(json.dumps(data["headers"]))
    elif conn_type == "url":
        doc["url"] = data.get("url", "")
    else:
        raise ValueError(f"Unsupported connection type: {conn_type}")

    connections.insert_one(doc)
    return _sanitize_conn(doc)


def test_connection(owner: str, conn_id: str) -> dict:
    """Test that a connection is reachable.  Returns {ok, message, latency_ms}."""
    doc = connections.find_one({"_id": conn_id, "owner": owner})
    if not doc:
        raise ValueError("Connection not found")
    start = time.time()
    try:
        if doc["type"] in SUPPORTED_DB_TYPES:
            engine = _make_engine(doc)
            with engine.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            engine.dispose()
        elif doc["type"] == "rest_api":
            url = doc["base_url"]
            _validate_url_safe(url)
            headers = json.loads(decrypt(doc["headers_enc"])) if doc.get("headers_enc") else {}
            resp = httpx.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
        elif doc["type"] == "url":
            _validate_url_safe(doc["url"])
            resp = httpx.head(doc["url"], timeout=10, follow_redirects=True)
            resp.raise_for_status()
        latency = round((time.time() - start) * 1000)
        return {"ok": True, "message": "Connection successful", "latency_ms": latency}
    except Exception as e:
        latency = round((time.time() - start) * 1000)
        return {"ok": False, "message": str(e), "latency_ms": latency}


def update_connection(owner: str, conn_id: str, data: dict) -> dict:
    doc = connections.find_one({"_id": conn_id, "owner": owner})
    if not doc:
        raise ValueError("Connection not found")
    updates = {"updated": datetime.now(timezone.utc).isoformat()}
    for key in ("name", "host", "port", "database", "username", "schema_name",
                "file_path", "dsn", "connection_string", "base_url", "json_path",
                "pagination_type", "page_param", "page_size_param", "page_size",
                "max_pages", "url"):
        if key in data:
            updates[key] = data[key]
    if data.get("password"):
        updates["password_enc"] = encrypt(data["password"])
    if data.get("headers"):
        updates["headers_enc"] = encrypt(json.dumps(data["headers"]))
    connections.update_one({"_id": conn_id}, {"$set": updates})
    doc.update(updates)
    return _sanitize_conn(doc)


def delete_connection(owner: str, conn_id: str) -> None:
    result = connections.delete_one({"_id": conn_id, "owner": owner})
    if result.deleted_count == 0:
        raise ValueError("Connection not found")


def list_connections(owner: str) -> list[dict]:
    return [_sanitize_conn(d) for d in connections.find({"owner": owner}).sort("created", -1)]


def get_connection(owner: str, conn_id: str) -> dict:
    doc = connections.find_one({"_id": conn_id, "owner": owner})
    if not doc:
        raise ValueError("Connection not found")
    return doc  # internal use – includes encrypted fields


# ── SQLAlchemy engine factory ─────────────────────────────────────
def _make_engine(doc: dict):
    import sqlalchemy as sa

    db_type = doc["type"]
    password = decrypt(doc["password_enc"]) if doc.get("password_enc") else ""
    user = doc.get("username", "")

    if db_type == "sqlite":
        url = f"sqlite:///{doc.get('file_path', '')}"
    elif db_type == "postgresql":
        url = sa.engine.URL.create("postgresql+psycopg2", user, password, doc["host"], doc.get("port") or 5432, doc["database"])
    elif db_type == "mysql":
        url = sa.engine.URL.create("mysql+pymysql", user, password, doc["host"], doc.get("port") or 3306, doc["database"])
    elif db_type == "mssql":
        url = sa.engine.URL.create("mssql+pyodbc", user, password, doc["host"], doc.get("port") or 1433, doc["database"],
                                   query={"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"})
    elif db_type == "odbc":
        if doc.get("connection_string"):
            url = f"mssql+pyodbc:///?odbc_connect={doc['connection_string']}"
        else:
            url = sa.engine.URL.create("mssql+pyodbc", user, password, doc["host"], doc.get("port"), doc["database"],
                                       query={"dsn": doc.get("dsn", "")})
    else:
        raise ValueError(f"Unsupported db type: {db_type}")

    return sa.create_engine(str(url) if not isinstance(url, str) else url,
                            connect_args={"connect_timeout": int(CONNECTOR_TIMEOUT_S)} if db_type != "sqlite" else {},
                            pool_pre_ping=True)


# ── Schema browser ────────────────────────────────────────────────
def browse_schema(owner: str, conn_id: str) -> dict:
    """Return schemas → tables → columns with types and approx row counts."""
    import sqlalchemy as sa

    doc = get_connection(owner, conn_id)
    engine = _make_engine(doc)
    inspector = sa.inspect(engine)

    result = {}
    try:
        schema_names = inspector.get_schema_names() if doc["type"] != "sqlite" else [None]
    except Exception:
        schema_names = [None]

    for schema in schema_names:
        schema_key = schema or "default"
        tables = []
        try:
            table_names = inspector.get_table_names(schema=schema)
        except Exception:
            table_names = []
        for tname in table_names[:200]:
            cols = []
            try:
                for col in inspector.get_columns(tname, schema=schema):
                    cols.append({"name": col["name"], "type": str(col["type"]), "nullable": col.get("nullable", True)})
            except Exception:
                pass
            # Approximate row count
            row_count = None
            try:
                with engine.connect() as conn:
                    row_count = conn.execute(sa.text(f"SELECT COUNT(*) FROM {tname}")).scalar()
            except Exception:
                pass
            tables.append({"name": tname, "columns": cols, "row_count": row_count})
        result[schema_key] = tables
    engine.dispose()
    return result


# ── Data pulling ──────────────────────────────────────────────────
def pull_data(owner: str, conn_id: str, *, table: str | None = None,
              sql: str | None = None, sample_mode: str = "full",
              sample_n: int = 1000, columns: list[str] | None = None,
              schema: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Pull data from a connection.  Returns (DataFrame, pull_metadata)."""
    import sqlalchemy as sa

    doc = get_connection(owner, conn_id)
    start = time.time()
    pull_meta = {"connection_id": conn_id, "started": datetime.now(timezone.utc).isoformat()}

    try:
        if doc["type"] in SUPPORTED_DB_TYPES:
            engine = _make_engine(doc)
            if sql:
                _assert_select_only(sql)
                query = sql
            elif table:
                qualified = f"{schema}.{table}" if schema and schema != "default" else table
                col_clause = ", ".join(f'"{c}"' for c in columns) if columns else "*"
                query = f"SELECT {col_clause} FROM {qualified}"
            else:
                raise ValueError("Provide either table or sql")

            if sample_mode == "first" and not sql:
                query += f" LIMIT {min(sample_n, CONNECTOR_ROW_CAP)}"
            elif sample_mode == "random" and not sql:
                query += f" ORDER BY RANDOM() LIMIT {min(sample_n, CONNECTOR_ROW_CAP)}"

            with engine.connect() as conn:
                df = pd.read_sql(sa.text(query), conn)
            engine.dispose()

        elif doc["type"] == "rest_api":
            df = _pull_rest_api(doc)

        elif doc["type"] == "url":
            df = _pull_url(doc)

        else:
            raise ValueError(f"Unsupported type: {doc['type']}")

        # Apply row cap
        if len(df) > CONNECTOR_ROW_CAP:
            df = df.head(CONNECTOR_ROW_CAP)

        # Apply column selection for non-SQL pulls
        if columns and doc["type"] not in SUPPORTED_DB_TYPES:
            valid_cols = [c for c in columns if c in df.columns]
            if valid_cols:
                df = df[valid_cols]

        duration = round(time.time() - start, 2)
        pull_meta.update({"rows": len(df), "cols": df.shape[1], "duration_s": duration, "status": "success"})

    except Exception as e:
        duration = round(time.time() - start, 2)
        pull_meta.update({"rows": 0, "cols": 0, "duration_s": duration, "status": "error", "error": str(e)})
        raise

    finally:
        pull_meta["finished"] = datetime.now(timezone.utc).isoformat()
        pull_history.insert_one({"_id": uuid.uuid4().hex[:12], "owner": owner, **pull_meta})

    return df, pull_meta


def _pull_rest_api(doc: dict) -> pd.DataFrame:
    """Pull data from a REST API with optional pagination."""
    url = doc["base_url"]
    _validate_url_safe(url)
    headers = json.loads(decrypt(doc["headers_enc"])) if doc.get("headers_enc") else {}
    json_path = doc.get("json_path", "data")
    pagination = doc.get("pagination_type", "none")
    all_records: list[dict] = []

    for page in range(1, doc.get("max_pages", 10) + 1):
        params = {}
        if pagination == "page_number":
            params[doc.get("page_param", "page")] = page
            params[doc.get("page_size_param", "per_page")] = doc.get("page_size", 100)

        resp = httpx.get(url, headers=headers, params=params, timeout=CONNECTOR_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()

        # Navigate JSON path
        records = data
        for key in json_path.split("."):
            if key and isinstance(records, dict):
                records = records.get(key, [])

        if not isinstance(records, list):
            records = [records] if records else []

        if not records:
            break
        all_records.extend(records)

        if pagination == "none" or len(records) < doc.get("page_size", 100):
            break

    return pd.DataFrame(all_records) if all_records else pd.DataFrame()


def _pull_url(doc: dict) -> pd.DataFrame:
    """Import a public CSV from a URL."""
    url = doc["url"]
    _validate_url_safe(url)
    resp = httpx.get(url, timeout=CONNECTOR_TIMEOUT_S, follow_redirects=True)
    resp.raise_for_status()
    import io
    content_type = resp.headers.get("content-type", "")
    if "json" in content_type:
        data = resp.json()
        if isinstance(data, list):
            return pd.DataFrame(data)
        return pd.DataFrame([data])
    # Default: CSV
    return pd.read_csv(io.StringIO(resp.text))


# ── Pull history ──────────────────────────────────────────────────
def get_pull_history(owner: str, conn_id: str | None = None, limit: int = 50) -> list[dict]:
    query: dict[str, Any] = {"owner": owner}
    if conn_id:
        query["connection_id"] = conn_id
    return list(pull_history.find(query).sort("started", -1).limit(limit))
