"""ETL pipeline engine.

Visual pipeline: Extract (Sources) → Transform (clean, join, filter, aggregate,
calculated column, pivot/unpivot, dedupe, type cast) → Load (dataset version,
Excel, CSV, Parquet, or database table).

Includes code generation (SQL, Python/pandas, R/tidyverse).
"""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..config import settings
from ..db import db
from ..services import datasets as ds_service

# ── MongoDB collections ────────────────────────────────────────────
etl_pipelines = db["etl_pipelines"]
etl_runs = db["etl_runs"]

# ── Step types ─────────────────────────────────────────────────────
EXTRACT_TYPES = ("dataset", "connection")
TRANSFORM_TYPES = (
    "clean", "join", "filter", "aggregate", "calculated_column",
    "pivot", "unpivot", "dedupe", "type_cast", "rename", "sort",
    "select_columns",
)
LOAD_TYPES = ("dataset_version", "csv", "excel", "parquet", "database")


# ── Pipeline CRUD ──────────────────────────────────────────────────

def create_pipeline(owner: str, data: dict) -> dict:
    doc = {
        "_id": uuid.uuid4().hex[:12],
        "owner": owner,
        "name": data["name"],
        "description": data.get("description", ""),
        "steps": data.get("steps", []),
        "parameters": data.get("parameters", []),
        "schedule": data.get("schedule"),
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    etl_pipelines.insert_one(doc)
    return doc


def get_pipeline(owner: str, pipeline_id: str) -> dict:
    doc = etl_pipelines.find_one({"_id": pipeline_id, "owner": owner})
    if not doc:
        raise ValueError("Pipeline not found")
    return doc


def list_pipelines(owner: str) -> list[dict]:
    return list(etl_pipelines.find({"owner": owner}).sort("created", -1))


def update_pipeline(owner: str, pipeline_id: str, updates: dict) -> dict:
    updates["updated"] = datetime.now(timezone.utc).isoformat()
    etl_pipelines.update_one({"_id": pipeline_id, "owner": owner}, {"$set": updates})
    return get_pipeline(owner, pipeline_id)


def delete_pipeline(owner: str, pipeline_id: str) -> None:
    result = etl_pipelines.delete_one({"_id": pipeline_id, "owner": owner})
    if result.deleted_count == 0:
        raise ValueError("Pipeline not found")


# ── Pipeline execution ─────────────────────────────────────────────

def run_pipeline(owner: str, pipeline_id: str,
                 params: dict | None = None,
                 datasets_map: dict[str, pd.DataFrame] | None = None) -> dict:
    """Execute a pipeline.  Returns a run record with step-by-step logs."""
    pipeline = get_pipeline(owner, pipeline_id)
    steps = pipeline["steps"]
    params = params or {}

    run_id = uuid.uuid4().hex[:12]
    run = {
        "_id": run_id,
        "pipeline_id": pipeline_id,
        "owner": owner,
        "started": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "parameters": params,
        "step_logs": [],
        "error": None,
    }

    # Working data: dict of name → DataFrame
    data: dict[str, pd.DataFrame] = dict(datasets_map or {})
    overall_start = time.time()

    try:
        for idx, step in enumerate(steps):
            step_start = time.time()
            step_log = {
                "index": idx,
                "type": step["type"],
                "name": step.get("name", step["type"]),
                "status": "running",
            }

            try:
                if step["type"] in EXTRACT_TYPES or step.get("category") == "extract":
                    _execute_extract(step, data, owner, params)
                elif step["type"] in TRANSFORM_TYPES or step.get("category") == "transform":
                    _execute_transform(step, data, params)
                elif step["type"] in LOAD_TYPES or step.get("category") == "load":
                    _execute_load(step, data, owner, params)
                else:
                    raise ValueError(f"Unknown step type: {step['type']}")

                duration = round(time.time() - step_start, 3)
                output_name = step.get("output", step.get("name", f"step_{idx}"))
                rows = len(data.get(output_name, pd.DataFrame()))
                step_log.update({"status": "success", "duration_s": duration, "rows_out": rows})

            except Exception as e:
                duration = round(time.time() - step_start, 3)
                step_log.update({"status": "error", "duration_s": duration, "error": str(e)})
                run["status"] = "failed"
                run["error"] = f"Step {idx} ({step.get('name', step['type'])}): {e}"
                run["step_logs"].append(step_log)
                break

            run["step_logs"].append(step_log)

        if run["status"] == "running":
            run["status"] = "success"

    except Exception as e:
        run["status"] = "failed"
        run["error"] = str(e)

    run["finished"] = datetime.now(timezone.utc).isoformat()
    run["duration_s"] = round(time.time() - overall_start, 2)

    # Store the final output DataFrames info
    run["outputs"] = {name: {"rows": len(df), "cols": df.shape[1]} for name, df in data.items()}

    etl_runs.insert_one(run)
    return run, data


def _execute_extract(step: dict, data: dict, owner: str, params: dict):
    """Extract step: load data from a dataset or connection."""
    output = step.get("output", step.get("name", "extract"))

    if step.get("dataset_id"):
        d = ds_service.get_dataset(owner, step["dataset_id"])
        df = ds_service.load_df(d)
        data[output] = df
    elif step.get("source_data"):
        # Inline data (for testing)
        data[output] = pd.DataFrame(step["source_data"])
    else:
        raise ValueError("Extract step needs dataset_id or source_data")


def _execute_transform(step: dict, data: dict, params: dict | None = None):
    """Execute a transform step on in-memory DataFrames."""
    params = params or {}
    step_type = step["type"]
    input_name = step.get("input", step.get("source"))
    output_name = step.get("output", input_name or step.get("name", "transform"))
    step_params = step.get("params", {})

    if input_name and input_name in data:
        df = data[input_name].copy()
    elif data:
        df = list(data.values())[-1].copy()
    else:
        raise ValueError(f"No input data for transform step '{step.get('name', step_type)}'")

    if step_type == "filter":
        expr = step_params.get("expression", "")
        if expr:
            # Substitute parameters
            for k, v in params.items():
                expr = expr.replace(f"${{{k}}}", str(v))
            df = df.query(expr)

    elif step_type == "aggregate":
        group_by = step_params.get("group_by", [])
        aggs = step_params.get("aggregations", {})
        if group_by and aggs:
            df = df.groupby(group_by, dropna=False).agg(aggs).reset_index()
            # Flatten multi-level columns
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(str(c) for c in col if c).strip("_") for col in df.columns]

    elif step_type == "join":
        right_name = step_params.get("right")
        if not right_name or right_name not in data:
            raise ValueError(f"Join: right table '{right_name}' not found")
        right_df = data[right_name]
        how = step_params.get("how", "left")
        left_on = step_params.get("left_on")
        right_on = step_params.get("right_on")
        df = df.merge(right_df, left_on=left_on, right_on=right_on, how=how, suffixes=("", "_right"))

    elif step_type == "calculated_column":
        col_name = step_params.get("name", "calculated")
        expr = step_params.get("expression", "")
        if expr:
            df[col_name] = df.eval(expr)

    elif step_type == "pivot":
        index = step_params.get("index")
        columns = step_params.get("columns")
        values = step_params.get("values")
        if index and columns and values:
            df = df.pivot_table(index=index, columns=columns, values=values, aggfunc="sum").reset_index()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(str(c) for c in col if c).strip("_") for col in df.columns]

    elif step_type == "unpivot":
        id_vars = step_params.get("id_vars", [])
        value_vars = step_params.get("value_vars", [])
        var_name = step_params.get("var_name", "variable")
        value_name = step_params.get("value_name", "value")
        df = pd.melt(df, id_vars=id_vars, value_vars=value_vars or None,
                     var_name=var_name, value_name=value_name)

    elif step_type == "dedupe":
        subset = step_params.get("subset")
        keep = step_params.get("keep", "first")
        df = df.drop_duplicates(subset=subset or None, keep=keep)

    elif step_type == "type_cast":
        casts = step_params.get("casts", {})
        for col, dtype in casts.items():
            if col in df.columns:
                if dtype == "datetime":
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                elif dtype == "numeric":
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif dtype == "string":
                    df[col] = df[col].astype(str)
                elif dtype == "int":
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    elif step_type == "rename":
        renames = step_params.get("renames", {})
        df = df.rename(columns=renames)

    elif step_type == "sort":
        by = step_params.get("by", [])
        ascending = step_params.get("ascending", True)
        if by:
            df = df.sort_values(by=by, ascending=ascending)

    elif step_type == "select_columns":
        cols = step_params.get("columns", [])
        if cols:
            df = df[[c for c in cols if c in df.columns]]

    elif step_type == "clean":
        # Delegate to the existing cleaning ops
        from ..services.cleaning_ops import apply_step
        op = step_params.get("op", "")
        op_params = step_params.get("params", {})
        if op:
            df = apply_step(df, {"op": op, "params": op_params})

    else:
        raise ValueError(f"Unknown transform type: {step_type}")

    data[output_name] = df


def _execute_load(step: dict, data: dict, owner: str, params: dict):
    """Execute a load step – save output data."""
    step_params = step.get("params", {})
    input_name = step.get("input") or (list(data.keys())[-1] if data else None)
    if not input_name or input_name not in data:
        raise ValueError("No data to load")

    df = data[input_name]
    load_type = step["type"]

    if load_type == "dataset_version":
        dataset_id = step_params.get("dataset_id")
        if dataset_id:
            d = ds_service.get_dataset(owner, dataset_id)
            ds_service.add_version(d, df, {"op": "pipeline_load", "params": {"pipeline_step": step.get("name", "")}})

    # File outputs are handled by the caller (router layer)


# ── Run history ────────────────────────────────────────────────────

def get_run_history(owner: str, pipeline_id: str, limit: int = 20) -> list[dict]:
    return list(etl_runs.find({"owner": owner, "pipeline_id": pipeline_id}).sort("started", -1).limit(limit))


def get_run(owner: str, run_id: str) -> dict:
    doc = etl_runs.find_one({"_id": run_id, "owner": owner})
    if not doc:
        raise ValueError("Run not found")
    return doc


# ── Code generation ────────────────────────────────────────────────

def export_as_python(pipeline: dict) -> str:
    """Generate equivalent Python (pandas) code for a pipeline."""
    lines = [
        '"""Auto-generated pipeline script from DataPilot."""',
        "import pandas as pd",
        "import numpy as np",
        "",
    ]

    for idx, step in enumerate(pipeline.get("steps", [])):
        step_type = step["type"]
        name = step.get("name", f"step_{idx}")
        p = step.get("params", {})
        output = step.get("output", name)
        input_name = step.get("input", "df")
        lines.append(f"# Step {idx + 1}: {name} ({step_type})")

        if step_type == "dataset" or step.get("category") == "extract":
            ds_id = step.get("dataset_id", "YOUR_DATASET")
            lines.append(f'{output} = pd.read_parquet("data/{ds_id}.parquet")  # Load source data')

        elif step_type == "filter":
            expr = p.get("expression", "")
            lines.append(f'{output} = {input_name}.query("{expr}")')

        elif step_type == "aggregate":
            group_by = p.get("group_by", [])
            aggs = p.get("aggregations", {})
            lines.append(f"{output} = {input_name}.groupby({group_by}).agg({aggs}).reset_index()")

        elif step_type == "join":
            right = p.get("right", "right_df")
            how = p.get("how", "left")
            left_on = p.get("left_on")
            right_on = p.get("right_on")
            lines.append(f'{output} = {input_name}.merge({right}, left_on="{left_on}", right_on="{right_on}", how="{how}")')

        elif step_type == "calculated_column":
            col = p.get("name", "new_col")
            expr = p.get("expression", "")
            lines.append(f'{output} = {input_name}.copy()')
            lines.append(f'{output}["{col}"] = {output}.eval("{expr}")')

        elif step_type == "pivot":
            lines.append(f'{output} = {input_name}.pivot_table(index="{p.get("index")}", columns="{p.get("columns")}", values="{p.get("values")}", aggfunc="sum").reset_index()')

        elif step_type == "unpivot":
            lines.append(f'{output} = pd.melt({input_name}, id_vars={p.get("id_vars", [])}, value_vars={p.get("value_vars", [])}, var_name="{p.get("var_name", "variable")}", value_name="{p.get("value_name", "value")}")')

        elif step_type == "dedupe":
            subset = p.get("subset")
            keep = p.get("keep", "first")
            lines.append(f'{output} = {input_name}.drop_duplicates(subset={subset}, keep="{keep}")')

        elif step_type == "type_cast":
            lines.append(f"{output} = {input_name}.copy()")
            for col, dtype in p.get("casts", {}).items():
                if dtype == "datetime":
                    lines.append(f'{output}["{col}"] = pd.to_datetime({output}["{col}"], errors="coerce")')
                elif dtype == "numeric":
                    lines.append(f'{output}["{col}"] = pd.to_numeric({output}["{col}"], errors="coerce")')
                elif dtype == "string":
                    lines.append(f'{output}["{col}"] = {output}["{col}"].astype(str)')

        elif step_type == "rename":
            lines.append(f"{output} = {input_name}.rename(columns={p.get('renames', {})})")

        elif step_type == "sort":
            lines.append(f'{output} = {input_name}.sort_values(by={p.get("by", [])}, ascending={p.get("ascending", True)})')

        elif step_type == "select_columns":
            lines.append(f'{output} = {input_name}[{p.get("columns", [])}]')

        else:
            lines.append(f"# {output} = ... (unsupported step type: {step_type})")

        lines.append("")

    lines.append(f'print(f"Pipeline complete. Final shape: {{{output}.shape}}")')
    lines.append(f'# {output}.to_csv("output.csv", index=False)')
    return "\n".join(lines)


def export_as_sql(pipeline: dict) -> str:
    """Generate equivalent SQL for a pipeline (best-effort)."""
    lines = ["-- Auto-generated SQL from DataPilot pipeline", ""]

    for idx, step in enumerate(pipeline.get("steps", [])):
        step_type = step["type"]
        name = step.get("name", f"step_{idx}")
        p = step.get("params", {})
        output = step.get("output", name).replace(" ", "_")
        input_name = step.get("input", "source_table").replace(" ", "_")
        lines.append(f"-- Step {idx + 1}: {name} ({step_type})")

        if step_type == "dataset" or step.get("category") == "extract":
            lines.append(f"-- Load from source: {step.get('dataset_id', 'source')}")
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT * FROM source_table;")

        elif step_type == "filter":
            expr = p.get("expression", "TRUE")
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT * FROM {input_name} WHERE {expr};")

        elif step_type == "aggregate":
            group_by = ", ".join(p.get("group_by", []))
            agg_parts = []
            for col, func in p.get("aggregations", {}).items():
                if isinstance(func, str):
                    agg_parts.append(f"{func.upper()}({col}) AS {col}_{func}")
                elif isinstance(func, list):
                    for f in func:
                        agg_parts.append(f"{f.upper()}({col}) AS {col}_{f}")
            agg_str = ", ".join(agg_parts) if agg_parts else "*"
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT {group_by}, {agg_str} FROM {input_name} GROUP BY {group_by};")

        elif step_type == "join":
            right = p.get("right", "right_table").replace(" ", "_")
            how = p.get("how", "LEFT").upper()
            left_on = p.get("left_on")
            right_on = p.get("right_on")
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT * FROM {input_name} {how} JOIN {right} ON {input_name}.{left_on} = {right}.{right_on};")

        elif step_type == "calculated_column":
            col = p.get("name", "new_col")
            expr = p.get("expression", "NULL")
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT *, ({expr}) AS {col} FROM {input_name};")

        elif step_type == "dedupe":
            subset = p.get("subset", [])
            partition = ", ".join(subset) if subset else "1"
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition} ORDER BY 1) AS rn FROM {input_name}) t WHERE rn = 1;")

        elif step_type == "sort":
            by = ", ".join(p.get("by", []))
            order = "ASC" if p.get("ascending", True) else "DESC"
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT * FROM {input_name} ORDER BY {by} {order};")

        elif step_type == "select_columns":
            cols = ", ".join(p.get("columns", ["*"]))
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT {cols} FROM {input_name};")

        elif step_type == "rename":
            renames = p.get("renames", {})
            alias_parts = [f'"{old}" AS "{new}"' for old, new in renames.items()]
            lines.append(f"CREATE TEMP TABLE {output} AS SELECT {', '.join(alias_parts)} FROM {input_name};")

        else:
            lines.append(f"-- Unsupported step type: {step_type}")

        lines.append("")

    return "\n".join(lines)


def export_as_r(pipeline: dict) -> str:
    """Generate equivalent R (tidyverse) code for a pipeline."""
    lines = [
        '# Auto-generated R script from DataPilot pipeline',
        'library(tidyverse)',
        'library(readr)',
        '',
    ]

    for idx, step in enumerate(pipeline.get("steps", [])):
        step_type = step["type"]
        name = step.get("name", f"step_{idx}")
        p = step.get("params", {})
        output = step.get("output", name).replace(" ", "_")
        input_name = step.get("input", "df").replace(" ", "_")
        lines.append(f"# Step {idx + 1}: {name} ({step_type})")

        if step_type == "dataset" or step.get("category") == "extract":
            lines.append(f'{output} <- read_csv("data/source.csv")')

        elif step_type == "filter":
            expr = p.get("expression", "TRUE")
            lines.append(f"{output} <- {input_name} %>% filter({expr})")

        elif step_type == "aggregate":
            group_by = ", ".join(p.get("group_by", []))
            agg_parts = []
            for col, func in p.get("aggregations", {}).items():
                if isinstance(func, str):
                    agg_parts.append(f"{col}_{func} = {func}({col}, na.rm = TRUE)")
            agg_str = ", ".join(agg_parts)
            lines.append(f"{output} <- {input_name} %>% group_by({group_by}) %>% summarise({agg_str})")

        elif step_type == "join":
            right = p.get("right", "right_df").replace(" ", "_")
            how = p.get("how", "left")
            left_on = p.get("left_on")
            right_on = p.get("right_on")
            join_func = f"{how}_join"
            lines.append(f'{output} <- {join_func}({input_name}, {right}, by = c("{left_on}" = "{right_on}"))')

        elif step_type == "calculated_column":
            col = p.get("name", "new_col")
            expr = p.get("expression", "NA")
            lines.append(f'{output} <- {input_name} %>% mutate({col} = {expr})')

        elif step_type == "dedupe":
            subset = p.get("subset", [])
            if subset:
                lines.append(f'{output} <- {input_name} %>% distinct({", ".join(subset)}, .keep_all = TRUE)')
            else:
                lines.append(f"{output} <- {input_name} %>% distinct()")

        elif step_type == "sort":
            by = p.get("by", [])
            asc = p.get("ascending", True)
            sort_cols = ", ".join(f"desc({c})" if not asc else c for c in by)
            lines.append(f"{output} <- {input_name} %>% arrange({sort_cols})")

        elif step_type == "select_columns":
            cols = ", ".join(p.get("columns", []))
            lines.append(f"{output} <- {input_name} %>% select({cols})")

        elif step_type == "rename":
            renames = p.get("renames", {})
            rename_parts = [f'"{v}" = "{k}"' for k, v in renames.items()]
            lines.append(f'{output} <- {input_name} %>% rename({", ".join(rename_parts)})')

        else:
            lines.append(f"# Unsupported step: {step_type}")

        lines.append("")

    lines.append(f'cat(sprintf("Pipeline complete. Final shape: %d x %d\\n", nrow({output}), ncol({output})))')
    return "\n".join(lines)
