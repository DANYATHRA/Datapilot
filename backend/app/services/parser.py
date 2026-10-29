import csv
import io
import json
import re
from typing import Any

import pandas as pd
from fastapi import HTTPException

from ..config import settings


class ParsingError(HTTPException):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=message)


def detect_magic_format(raw: bytes) -> str | None:
    """Inspect file header bytes to identify format."""
    if not raw or len(raw) < 4:
        return None
    # Parquet starts with PAR1
    if raw.startswith(b"PAR1"):
        return "parquet"
    # ZIP / XLSX starts with PK\x03\x04
    if raw.startswith(b"PK\x03\x04"):
        return "xlsx"
    # Legacy XLS compound document header
    if raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"
    # JSON usually begins with whitespace followed by [ or {
    stripped = raw[:100].lstrip()
    if stripped.startswith((b"[", b"{")):
        return "json"
    # If it is mostly printable text/utf8, could be CSV
    return "csv"


def list_excel_sheets(raw: bytes, filename: str = "file.xlsx") -> list[str]:
    """Inspect an Excel workbook in memory and return all worksheet names."""
    low = filename.lower()
    bio = io.BytesIO(raw)
    try:
        if low.endswith(".xls") or raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            import xlrd
            wb = xlrd.open_workbook(file_contents=raw)
            return wb.sheet_names()
        else:
            import openpyxl
            wb = openpyxl.load_workbook(bio, read_only=True, keep_links=False)
            return wb.sheetnames
    except Exception as e:
        raise ParsingError(f"Failed to inspect Excel worksheets: {e}")


def sniff_csv_delimiter(sample_text: str) -> str:
    """Auto-detect CSV delimiter from sample text."""
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample_text, delimiters=",\t;|:")
        return dialect.delimiter
    except Exception:
        # Fallback frequency count in first line
        first_line = sample_text.splitlines()[0] if sample_text.splitlines() else ""
        counts = {d: first_line.count(d) for d in [",", "\t", ";", "|"]}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


def decode_text_bytes(raw: bytes) -> tuple[str, str]:
    """Decode bytes testing UTF-8 BOM, standard UTF-8, Latin-1, and Windows CP1252."""
    for enc in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
        try:
            text = raw.decode(enc)
            return text, enc
        except UnicodeDecodeError:
            continue
    raise ParsingError("Unable to decode file text. Unsupported text encoding.")


def parse_csv(raw: bytes, null_markers: list[str] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse CSV text with delimiter and encoding detection while preserving leading zeros."""
    text, enc = decode_text_bytes(raw)
    if not text.strip():
        raise ParsingError("CSV file is completely empty.")

    sample = text[:8192]
    delimiter = sniff_csv_delimiter(sample)

    na_vals = ["", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan",
               "1.#IND", "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"]
    if null_markers:
        na_vals = list(set(na_vals + [str(m).strip() for m in null_markers]))

    try:
        # Use python engine with keep_default_na to preserve strings and prevent losing leading zeros
        df = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            na_values=na_vals,
            keep_default_na=True,
            dtype=object,  # read as object first to preserve leading zeros in codes/IDs
            engine="python"
        )
    except Exception as e:
        raise ParsingError(f"Malformed CSV content: {e}")

    from .complete_cleaner import clean_structure_preamble_and_headers
    df, _ = clean_structure_preamble_and_headers(df)

    # Convert object columns to numeric/datetime if purely numerical (except if column has leading zeros)
    df = infer_best_types(df)

    column_currencies = {}
    for c in df.columns:
        s_vals = df[c].dropna().astype(str)
        if not s_vals.empty:
            for sym in ["₹", "$", "€", "£", "¥"]:
                if s_vals.str.contains(sym, regex=False).any():
                    column_currencies[str(c)] = sym
                    break

    meta = {
        "format": "csv",
        "encoding": enc,
        "delimiter": delimiter,
        "rows": len(df),
        "cols": df.shape[1],
        "size_bytes": len(raw),
        "column_currencies": column_currencies,
    }
    return df, meta


def infer_best_types(df: pd.DataFrame) -> pd.DataFrame:
    """Safely convert columns from object to numeric where appropriate, preserving leading zeros."""
    df = df.copy()
    for col in df.columns:
        s = df[col]
        non_null = s.dropna().astype(str).str.strip()
        if non_null.empty:
            continue
        # Check if column has leading zeros on multi-digit numbers (like '00123' or '05')
        has_leading_zeros = (
            non_null.str.match(r"^0\d+$").any()
            or (non_null.str.match(r"^\+?\d+$").any() and (col.lower() in ("phone", "zip", "pin", "code", "id", "pan", "ssn", "mobile", "aadhaar")))
        )
        if has_leading_zeros:
            # Preserve as text
            df[col] = df[col].astype("string").where(df[col].notna(), None)
            continue

        # Try numeric conversion
        numeric_s = pd.to_numeric(s, errors="coerce")
        if numeric_s.notna().sum() == non_null.shape[0]:
            # Convert to int if all integers
            if (numeric_s.dropna() % 1 == 0).all() and (numeric_s.dropna() <= 2**53).all():
                try:
                    df[col] = numeric_s.round().astype("Int64")
                    continue
                except Exception:
                    pass
            df[col] = numeric_s.astype(float)
        else:
            # Keep as string object
            df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


def parse_excel(raw: bytes, filename: str, sheet_name: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse Excel workbook with worksheet selection and sheet discovery."""
    sheets = list_excel_sheets(raw, filename)
    if not sheets:
        raise ParsingError("Excel workbook contains no readable worksheets.")

    if not sheet_name:
        # Re-uploading a previously exported cleaned .xlsx: read Cleaned_Data, ignore extra sheets
        if "Cleaned_Data" in sheets:
            target_sheet = "Cleaned_Data"
        else:
            target_sheet = sheets[0]
    else:
        target_sheet = sheet_name if sheet_name in sheets else sheets[0]

    bio = io.BytesIO(raw)
    try:
        # If XLSX, inspect and unmerge merged cells before reading
        if filename.lower().endswith(".xlsx") or not filename.lower().endswith(".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
                ws = wb[target_sheet] if target_sheet in wb.sheetnames else wb.active
                # Unmerge and forward-fill down/right
                merged_ranges = list(ws.merged_cells.ranges)
                for rng in merged_ranges:
                    top_val = ws.cell(row=rng.min_row, column=rng.min_col).value
                    ws.unmerge_cells(str(rng))
                    for r in range(rng.min_row, rng.max_row + 1):
                        for c in range(rng.min_col, rng.max_col + 1):
                            ws.cell(row=r, column=c, value=top_val)
                data = list(ws.values)
                if data and len(data) > 1:
                    df = pd.DataFrame(data[1:], columns=data[0])
                else:
                    df = pd.read_excel(bio, sheet_name=target_sheet, dtype=object)
            except Exception:
                bio.seek(0)
                df = pd.read_excel(bio, sheet_name=target_sheet, dtype=object)
        else:
            df = pd.read_excel(bio, sheet_name=target_sheet, dtype=object)
    except Exception as e:
        raise ParsingError(f"Could not read Excel worksheet '{target_sheet}': {e}")

    # Check and clean structure preamble (title rows above header)
    from .complete_cleaner import clean_structure_preamble_and_headers
    df, _ = clean_structure_preamble_and_headers(df)

    # Detect currency symbols before numeric conversion
    column_currencies = {}
    for c in df.columns:
        s_vals = df[c].dropna().astype(str)
        if not s_vals.empty:
            for sym in ["₹", "$", "€", "£", "¥"]:
                if s_vals.str.contains(sym, regex=False).any():
                    column_currencies[str(c)] = sym
                    break

    df = infer_best_types(df)
    meta = {
        "format": "xlsx" if filename.lower().endswith(".xlsx") else "xls",
        "sheet_name": target_sheet,
        "available_sheets": sheets,
        "rows": len(df),
        "cols": df.shape[1],
        "size_bytes": len(raw),
        "column_currencies": column_currencies,
    }
    return df, meta


def parse_json(raw: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse JSON tabular data (array of objects or records)."""
    text, enc = decode_text_bytes(raw)
    try:
        data = json.loads(text)
    except Exception as e:
        raise ParsingError(f"Invalid JSON syntax: {e}")

    if isinstance(data, list):
        if not data:
            raise ParsingError("JSON array is empty.")
        if not all(isinstance(item, dict) for item in data):
            raise ParsingError("JSON must be an array of objects/records.")
        # Check for non-scalar nested values to report clear error
        has_nested = any(
            any(isinstance(v, (dict, list)) for v in item.values())
            for item in data[:50]
        )
        if has_nested:
            # Flatten one level or stringify
            import json as _j
            flattened = []
            for item in data:
                flat_item = {}
                for k, v in item.items():
                    flat_item[k] = _j.dumps(v) if isinstance(v, (dict, list)) else v
                flattened.append(flat_item)
            df = pd.DataFrame(flattened)
        else:
            df = pd.DataFrame(data)
    elif isinstance(data, dict):
        # Could be columnar: {"col1": [1, 2], "col2": [3, 4]}
        try:
            df = pd.DataFrame(data)
        except Exception:
            raise ParsingError("Hierarchical JSON objects without an array of records are not tabular.")
    else:
        raise ParsingError("Expected a JSON array of objects.")

    df = infer_best_types(df)
    meta = {
        "format": "json",
        "encoding": enc,
        "rows": len(df),
        "cols": df.shape[1],
        "size_bytes": len(raw),
    }
    return df, meta


def parse_parquet(raw: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse Parquet file."""
    bio = io.BytesIO(raw)
    try:
        df = pd.read_parquet(bio)
    except Exception as e:
        raise ParsingError(f"Invalid or corrupted Parquet file: {e}")

    meta = {
        "format": "parquet",
        "rows": len(df),
        "cols": df.shape[1],
        "size_bytes": len(raw),
    }
    return df, meta


def parse_uploaded_file(
    filename: str,
    raw: bytes,
    sheet_name: str | None = None,
    null_markers: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Master entrypoint to validate and parse raw uploaded dataset."""
    if not raw or len(raw) == 0:
        raise ParsingError("Uploaded file is empty (0 bytes).")

    max_mb = settings.MAX_UPLOAD_MB
    if len(raw) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File size ({round(len(raw) / (1024*1024), 2)} MB) exceeds limit of {max_mb} MB.")

    magic = detect_magic_format(raw)
    low = filename.lower()

    if low.endswith(".parquet") or magic == "parquet":
        df, meta = parse_parquet(raw)
    elif low.endswith((".xlsx", ".xlsm", ".xls")) or magic in ("xlsx", "xls"):
        df, meta = parse_excel(raw, filename, sheet_name)
    elif low.endswith(".json") or magic == "json":
        df, meta = parse_json(raw)
    elif low.endswith((".csv", ".txt")) or magic == "csv":
        df, meta = parse_csv(raw, null_markers)
    else:
        # Try CSV as universal fallback
        try:
            df, meta = parse_csv(raw, null_markers)
        except Exception:
            raise ParsingError("Unsupported file format. Please upload CSV, XLSX, XLS, JSON, or Parquet.")

    if df.empty or df.shape[1] == 0:
        raise ParsingError("Parsed dataset contains 0 rows or 0 columns.")

    meta["filename"] = filename
    return df, meta
