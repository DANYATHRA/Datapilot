import io
import json
import urllib.parse
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth import current_user
from ..config import settings
from ..db import datasets
from ..services import cleaning_engine, datasets as ds
from ..services.parser import list_excel_sheets, parse_uploaded_file
from ..services.profiling import profile
from ..services.util import to_json_table

router = APIRouter(prefix="/data-cleaning", tags=["data-cleaning"])


def _sanitize_json_obj(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=lambda o: int(o) if isinstance(o, (np.integer,)) else (float(o) if isinstance(o, (np.floating,)) else (bool(o) if isinstance(o, (np.bool_,)) else str(o)))))


class CleanStep(BaseModel):
    op: str
    params: dict[str, Any] = {}


class CleanRequest(BaseModel):
    step: CleanStep | None = None
    steps: list[CleanStep] | None = None
    from_version: int | None = 1  # default to original v1 to avoid unintentional repeat mutations
    dry_run: bool = False


@router.post("/inspect-sheets")
async def inspect_sheets(file: UploadFile = File(...), user=Depends(current_user)):
    """Inspect sheets of an Excel workbook before uploading."""
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB} MB")
    try:
        sheets = list_excel_sheets(raw, file.filename or "file.xlsx")
        return {"filename": file.filename, "sheets": sheets}
    except Exception as e:
        raise HTTPException(400, f"Could not inspect sheets: {e}")


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    null_markers: str | None = Form(None),
    user=Depends(current_user),
):
    """Upload and parse a dataset in CSV, Excel (XLSX/XLS), JSON, or Parquet."""
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB} MB")

    custom_nulls = [m.strip() for m in null_markers.split(",")] if null_markers else None
    df, meta = parse_uploaded_file(file.filename or "dataset.csv", raw, sheet_name=sheet_name, null_markers=custom_nulls)

    doc = ds.create_dataset(user["_id"], file.filename or "dataset.csv", df)
    # Store initial parser metadata
    datasets.update_one({"_id": doc["_id"]}, {"$set": {"source_meta": meta}})
    return {
        "id": doc["_id"],
        "dataset_id": doc["_id"],
        "name": doc["name"],
        "table": doc["table"],
        "current_version": doc["current_version"],
        "rows": len(df),
        "cols": df.shape[1],
        "meta": meta,
    }


SAMPLE_DIR = Path(__file__).resolve().parents[3] / "sample_data"
ALLOWED_SAMPLES = {"sales.csv", "survey.csv", "students.xlsx", "datapilot_test_sales.xlsx"}


@router.post("/load-sample")
def load_sample_dataset(sample_name: str = "sales.csv", user=Depends(current_user)):
    """Load a bundled sample dataset (sales.csv or survey.csv) for instant cleaning demonstration."""
    if sample_name not in ALLOWED_SAMPLES:
        raise HTTPException(400, f"Sample '{sample_name}' not available. Allowed: {sorted(ALLOWED_SAMPLES)}")
    sample_path = SAMPLE_DIR / sample_name
    if not sample_path.exists():
        raise HTTPException(404, f"Sample file {sample_name} not found.")
    raw = sample_path.read_bytes()
    df, meta = parse_uploaded_file(sample_name, raw)
    doc = ds.create_dataset(user["_id"], sample_name, df)
    datasets.update_one({"_id": doc["_id"]}, {"$set": {"source_meta": meta}})
    return {
        "id": doc["_id"],
        "dataset_id": doc["_id"],
        "name": doc["name"],
        "table": doc["table"],
        "current_version": doc["current_version"],
        "rows": len(df),
        "cols": df.shape[1],
        "meta": meta,
    }


@router.get("/{ds_id}/profile")
def get_dataset_profile(ds_id: str, version: int | None = None, user=Depends(current_user)):
    """Generate detailed data quality profile for dataset version."""
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d, version)
    return profile(df)


@router.post("/{ds_id}/preview")
def preview_cleaning(ds_id: str, body: CleanRequest, user=Depends(current_user)):
    """Preview proposed cleaning operations without applying them."""
    d = ds.get_dataset(user["_id"], ds_id)
    source_v = body.from_version or 1  # preview from original v1 by default
    original_df = ds.load_df(d, source_v)

    steps_to_run = body.steps if body.steps else ([body.step] if body.step else [])
    if not steps_to_run:
        raise HTTPException(400, "No cleaning steps provided for preview.")

    raw_steps = [{"op": s.op, "params": s.params} for s in steps_to_run]
    try:
        cleaned_df, logs, summary = cleaning_engine.execute_recipe(original_df, raw_steps)
    except Exception as e:
        raise HTTPException(400, f"Preview failed: {e}")

    # Detect destructive warnings
    warnings = []
    if summary["rows_removed"] > 0:
        warnings.append(f"Destructive operation: {summary['rows_removed']} row(s) will be deleted.")
    if summary["cols_removed"] > 0:
        warnings.append(f"Destructive operation: {summary['cols_removed']} column(s) will be dropped.")

    return {
        "dry_run": True,
        "summary": _sanitize_json_obj(summary),
        "destructive_warnings": warnings,
        "preview_before": to_json_table(original_df, 15),
        "preview_after": to_json_table(cleaned_df, 15),
        "operations": _sanitize_json_obj(logs),
    }


@router.post("/{ds_id}/clean")
def execute_cleaning(ds_id: str, body: CleanRequest, user=Depends(current_user)):
    """Execute selected cleaning operations and create a new version with audit report."""
    d = ds.get_dataset(user["_id"], ds_id)
    source_v = body.from_version or 1
    original_df = ds.load_df(d, source_v)

    steps_to_run = body.steps if body.steps else ([body.step] if body.step else [])
    if not steps_to_run:
        raise HTTPException(400, "No cleaning steps provided.")

    raw_steps = [{"op": s.op, "params": s.params} for s in steps_to_run]
    try:
        cleaned_df, logs, summary = cleaning_engine.execute_recipe(original_df, raw_steps)
    except Exception as e:
        raise HTTPException(400, f"Cleaning failed: {e}")

    if body.dry_run:
        return {
            "dry_run": True,
            "summary": summary,
            "preview": to_json_table(cleaned_df, 20),
            "operations": logs,
        }

    # Generate full cleaning report and CSV log
    report = cleaning_engine.generate_cleaning_report(
        dataset_id=ds_id,
        original_filename=d["name"],
        original_df=original_df,
        cleaned_df=cleaned_df,
        logs=logs,
        summary=summary,
    )
    log_csv = cleaning_engine.generate_transformation_log_csv(logs)

    # Add as new immutable version in Datapilot
    step_doc = {
        "op": "batch_clean" if len(raw_steps) > 1 else raw_steps[0]["op"],
        "params": {"steps_count": len(raw_steps), "source_version": source_v},
    }
    new_v = ds.add_version(d, cleaned_df, step_doc)

    report = _sanitize_json_obj(report)
    summary = _sanitize_json_obj(summary)
    logs = _sanitize_json_obj(logs)

    # Persist report & log in MongoDB and disk
    report_path = ds.vpath(user["_id"], ds_id, new_v).parent / f"report_v{new_v}.json"
    log_path = ds.vpath(user["_id"], ds_id, new_v).parent / f"log_v{new_v}.csv"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log_csv)

    datasets.update_one(
        {"_id": ds_id},
        {"$set": {"last_cleaning_report": report, f"reports_by_version.{new_v}": report}}
    )

    return {
        "dry_run": False,
        "version": new_v,
        "summary": summary,
        "report": report,
        "operations": logs,
    }


@router.get("/{ds_id}/report")
def get_cleaning_report(ds_id: str, version: int | None = None, download: bool = False, user=Depends(current_user)):
    """Retrieve or download cleaning report as JSON."""
    d = ds.get_dataset(user["_id"], ds_id)
    v = version or d["current_version"]
    report = d.get(f"reports_by_version", {}).get(str(v)) or d.get("last_cleaning_report")

    if not report:
        # Generate on-the-fly comparing v1 to version v
        v1_df = ds.load_df(d, 1)
        cur_df = ds.load_df(d, v)
        summary = {
            "rows_before": len(v1_df),
            "rows_after": len(cur_df),
            "rows_removed": len(v1_df) - len(cur_df),
            "cols_before": v1_df.shape[1],
            "cols_after": cur_df.shape[1],
            "cols_removed": v1_df.shape[1] - cur_df.shape[1],
            "nulls_before": int(v1_df.isna().sum().sum()),
            "nulls_after": int(cur_df.isna().sum().sum()),
            "nulls_resolved": int(v1_df.isna().sum().sum()) - int(cur_df.isna().sum().sum()),
            "duplicates_before": int(v1_df.duplicated().sum()),
            "duplicates_after": int(cur_df.duplicated().sum()),
            "duplicates_removed": int(v1_df.duplicated().sum()) - int(cur_df.duplicated().sum()),
        }
        report = cleaning_engine.generate_cleaning_report(
            dataset_id=ds_id,
            original_filename=d["name"],
            original_df=v1_df,
            cleaned_df=cur_df,
            logs=[v.get("step", {}) for v in d.get("versions", [])],
            summary=summary,
        )

    if download:
        content = json.dumps(report, indent=2).encode("utf-8")
        filename = f"cleaning_report_{ds_id}.json"
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    return report


@router.get("/{ds_id}/log")
def get_transformation_log(ds_id: str, version: int | None = None, user=Depends(current_user)):
    """Download transformation log as CSV."""
    d = ds.get_dataset(user["_id"], ds_id)
    v = version or d["current_version"]
    log_path = ds.vpath(user["_id"], ds_id, v).parent / f"log_v{v}.csv"

    if log_path.exists():
        content = log_path.read_text(encoding="utf-8")
    else:
        # Reconstruct from versions audit trail
        logs = []
        for idx, ver_entry in enumerate(d.get("versions", []), 1):
            step = ver_entry.get("step", {})
            logs.append({
                "order": idx,
                "operation": step.get("op", "unknown"),
                "columns": step.get("params", {}).get("columns", []),
                **step.get("params", {}),
                "rows_affected": ver_entry.get("rows_before", ver_entry.get("rows", 0)) - ver_entry.get("rows", 0),
                "values_affected": 0,
                "reason": f"Version {ver_entry.get('v')}",
                "timestamp": ver_entry.get("created", ""),
            })
        content = cleaning_engine.generate_transformation_log_csv(logs)

    filename = f"cleaning_log_{ds_id}.csv"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/{ds_id}/download")
def download_cleaned_data(
    ds_id: str,
    format: str = Query("csv", pattern="^(csv|xlsx|json|parquet)$"),
    version: int | None = None,
    user=Depends(current_user),
):
    """Download the actual cleaned dataset file in selected format (CSV, XLSX, JSON, Parquet)."""
    d = ds.get_dataset(user["_id"], ds_id)
    v = version or d["current_version"]
    df = ds.load_df(d, v)

    # Derive safe base filename
    base_name = d["name"]
    for ext in [".csv", ".xlsx", ".xls", ".json", ".parquet", ".txt"]:
        if base_name.lower().endswith(ext):
            base_name = base_name[:-len(ext)]
            break
    clean_filename = f"cleaned_{base_name}.{format}"
    quoted_filename = urllib.parse.quote(clean_filename)

    buf = io.BytesIO()

    if format == "csv":
        df.to_csv(buf, index=False, encoding="utf-8")
        media_type = "text/csv; charset=utf-8"
    elif format == "xlsx":
        df.to_excel(buf, index=False)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format == "json":
        # Export as clean JSON array of records
        json_str = df.to_json(orient="records", date_format="iso", indent=2)
        buf.write(json_str.encode("utf-8"))
        media_type = "application/json; charset=utf-8"
    elif format == "parquet":
        df.to_parquet(buf, index=False)
        media_type = "application/octet-stream"
    else:
        raise HTTPException(400, f"Unsupported download format '{format}'.")

    buf.seek(0)
    headers = {
        "Content-Disposition": f'attachment; filename="{clean_filename}"; filename*=UTF-8\'\'{quoted_filename}',
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return Response(content=buf.getvalue(), media_type=media_type, headers=headers)


class UpdateCellReq(BaseModel):
    row_index: int
    column: str
    value: Any = None


class ImputeColumnReq(BaseModel):
    column: str
    strategy: str  # "mean", "median", "mode", "zero", "custom", "auto"
    custom_value: Any = None


@router.post("/{ds_id}/update-cell")
def update_cell(ds_id: str, body: UpdateCellReq, user=Depends(current_user)):
    """Directly update a single cell value in the dataset and save as a new immutable version."""
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)

    col = body.column
    if col not in df.columns:
        raise HTTPException(400, f"Column '{col}' not found in dataset.")

    if body.row_index < 0 or body.row_index >= len(df):
        raise HTTPException(400, f"Row index {body.row_index} out of bounds (0 to {len(df)-1}).")

    val = body.value
    # Convert empty strings to None/nan
    if val == "" or val is None:
        if pd.api.types.is_numeric_dtype(df[col]):
            val = np.nan
        else:
            val = None
    else:
        # Try type conversion to match column dtype
        if pd.api.types.is_integer_dtype(df[col]):
            try:
                val = int(val)
            except Exception:
                pass
        elif pd.api.types.is_float_dtype(df[col]):
            try:
                val = float(val)
            except Exception:
                pass

    df.at[body.row_index, col] = val

    step_doc = {
        "op": "update_cell",
        "params": {
            "row": body.row_index,
            "column": col,
            "value": str(val) if val is not None else None,
        },
    }
    new_v = ds.add_version(d, df, step_doc)
    return {
        "ok": True,
        "version": new_v,
        "row_index": body.row_index,
        "column": col,
        "value": val if not (isinstance(val, float) and np.isnan(val)) else None,
    }


@router.post("/{ds_id}/impute-column")
def impute_column(ds_id: str, body: ImputeColumnReq, user=Depends(current_user)):
    """Impute missing values in a column using mean, median, mode, zero, custom, or auto strategy."""
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)

    col = body.column
    if col not in df.columns:
        raise HTTPException(400, f"Column '{col}' not found in dataset.")

    series = df[col]
    missing_mask = series.isna() | (
        series.astype(str).str.strip().isin(["", "nan", "NaN", "null", "None"])
    )
    missing_count = int(missing_mask.sum())

    if missing_count == 0:
        return {"ok": True, "imputed_count": 0, "message": "No missing values found in column."}

    strategy = body.strategy.lower()
    fill_val = None

    if strategy == "mean":
        num_series = pd.to_numeric(series, errors="coerce")
        fill_val = round(float(num_series.mean()), 2) if not num_series.dropna().empty else 0.0
    elif strategy == "median":
        num_series = pd.to_numeric(series, errors="coerce")
        fill_val = round(float(num_series.median()), 2) if not num_series.dropna().empty else 0.0
    elif strategy == "mode":
        clean_s = series[~missing_mask]
        fill_val = clean_s.mode()[0] if not clean_s.empty else "Unknown"
    elif strategy == "zero":
        fill_val = 0 if pd.api.types.is_numeric_dtype(series) else "0"
    elif strategy == "custom":
        fill_val = body.custom_value
    elif strategy == "auto":
        # Smart choice: median if numeric, mode if text/categorical
        if pd.api.types.is_numeric_dtype(series):
            num_series = pd.to_numeric(series, errors="coerce")
            fill_val = round(float(num_series.median()), 2) if not num_series.dropna().empty else 0.0
        else:
            clean_s = series[~missing_mask]
            fill_val = clean_s.mode()[0] if not clean_s.empty else "Unknown"
    else:
        raise HTTPException(400, f"Unsupported imputation strategy '{strategy}'.")

    # Match numeric type if needed
    if pd.api.types.is_numeric_dtype(series):
        try:
            fill_val = float(fill_val)
        except Exception:
            pass

    df.loc[missing_mask, col] = fill_val

    step_doc = {
        "op": "impute_column",
        "params": {
            "column": col,
            "strategy": strategy,
            "imputed_count": missing_count,
            "fill_value": str(fill_val),
        },
    }
    new_v = ds.add_version(d, df, step_doc)
    return {
        "ok": True,
        "version": new_v,
        "imputed_count": missing_count,
        "fill_value": fill_val,
        "column": col,
    }


@router.get("/{ds_id}/imputation-suggestions")
def get_imputation_suggestions(ds_id: str, user=Depends(current_user)):
    """Return smart imputation suggestions (mean, median, mode, auto) for each column with missing values."""
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)

    suggestions = {}
    for col in df.columns:
        s = df[col]
        missing_mask = s.isna() | (
            s.astype(str).str.strip().isin(["", "nan", "NaN", "null", "None"])
        )
        missing_count = int(missing_mask.sum())
        clean_s = s[~missing_mask]

        is_num = pd.api.types.is_numeric_dtype(s)
        mean_val = None
        median_val = None
        mode_val = None
        auto_val = None

        if is_num:
            num_s = pd.to_numeric(clean_s, errors="coerce").dropna()
            if not num_s.empty:
                mean_val = round(float(num_s.mean()), 2)
                median_val = round(float(num_s.median()), 2)
                mode_val = round(float(num_s.mode()[0]), 2) if not num_s.mode().empty else median_val
                auto_val = median_val
            else:
                mean_val = median_val = mode_val = auto_val = 0
        else:
            if not clean_s.empty and not clean_s.mode().empty:
                mode_val = str(clean_s.mode()[0])
            else:
                mode_val = "Unknown"
            auto_val = mode_val

        suggestions[col] = {
            "is_numeric": is_num,
            "missing_count": missing_count,
            "missing_pct": round(missing_count / len(df) * 100, 1) if len(df) else 0,
            "mean": mean_val,
            "median": median_val,
            "mode": mode_val,
            "auto": auto_val,
        }
    return suggestions
