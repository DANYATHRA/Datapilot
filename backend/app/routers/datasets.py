import datetime as dt
import io
import re
from typing import Any
import urllib.parse
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import numpy as np
import pandas as pd
from pydantic import BaseModel

from ..auth import current_user
from ..config import settings
from ..db import dashboards, datasets, queries
from ..services import cleaning_ops, datasets as ds
from ..services.profiling import profile
from ..services.util import to_json_table

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _brief(d):
    cur = next(v for v in d["versions"] if v["v"] == d["current_version"])
    return {"id": d["_id"], "name": d["name"], "table": d["table"], "current_version": d["current_version"],
            "rows": cur["rows"], "cols": cur["cols"], "created": d["created"]}


@router.get("")
def list_datasets(user=Depends(current_user)):
    return [_brief(d) for d in datasets.find({"owner": user["_id"]}).sort("created", -1)]


@router.post("/upload")
async def upload(file: UploadFile = File(...), user=Depends(current_user)):
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB} MB")
    df = ds.read_upload(file.filename or "dataset.csv", raw)
    if df.empty or df.shape[1] == 0:
        raise HTTPException(400, "File has no data")
    doc = ds.create_dataset(user["_id"], file.filename or "dataset.csv", df)
    return _brief(doc)


@router.get("/{ds_id}")
def get_one(ds_id: str, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    return {**_brief(d), "versions": d["versions"]}


@router.delete("/{ds_id}")
def delete(ds_id: str, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    import shutil
    shutil.rmtree(settings.DATA_DIR / user["_id"] / ds_id, ignore_errors=True)
    datasets.delete_one({"_id": d["_id"]})
    return {"deleted": ds_id}


@router.get("/{ds_id}/preview")
def preview(ds_id: str, n: int = 50, version: int | None = None, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d, version)
    return {**to_json_table(df, min(n, 500)), "total_rows": len(df)}


@router.get("/{ds_id}/profile")
def get_profile(ds_id: str, version: int | None = None, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    return profile(ds.load_df(d, version))


@router.get("/{ds_id}/suggestions")
def suggestions(ds_id: str, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    return cleaning_ops.suggest(ds.load_df(d))


class StepIn(BaseModel):
    op: str
    params: dict = {}
    dry_run: bool = False


@router.post("/{ds_id}/clean")
def clean(ds_id: str, step: StepIn, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    before = ds.load_df(d)
    try:
        after = cleaning_ops.apply_step(before, {"op": step.op, "params": step.params})
    except (cleaning_ops.CleaningError, KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, f"Step failed: {e}")
    summary = {"rows_before": len(before), "rows_after": len(after),
               "nulls_before": int(before.isna().sum().sum()), "nulls_after": int(after.isna().sum().sum()),
               "cols_before": before.shape[1], "cols_after": after.shape[1]}
    if step.dry_run:
        return {"dry_run": True, "summary": summary, "preview": to_json_table(after, 20)}
    v = ds.add_version(d, after, {"op": step.op, "params": step.params})
    return {"dry_run": False, "version": v, "summary": summary}


class RollbackIn(BaseModel):
    version: int


@router.post("/{ds_id}/rollback")
def rollback(ds_id: str, body: RollbackIn, user=Depends(current_user)):
    """Non-destructive: copies an older version forward as a new version, keeping the full history."""
    d = ds.get_dataset(user["_id"], ds_id)
    if body.version not in {v["v"] for v in d["versions"]}:
        raise HTTPException(404, "Version not found")
    v = ds.add_version(d, ds.load_df(d, body.version),
                       {"op": "rollback", "params": {"to_version": body.version}})
    return {"version": v}


@router.get("/{ds_id}/diff")
def diff(ds_id: str, a: int, b: int, user=Depends(current_user)):
    d = ds.get_dataset(user["_id"], ds_id)
    da, db_ = ds.load_df(d, a), ds.load_df(d, b)
    common = [c for c in da.columns if c in db_.columns]
    return {"rows": {"a": len(da), "b": len(db_)},
            "columns_added": [c for c in db_.columns if c not in da.columns],
            "columns_removed": [c for c in da.columns if c not in db_.columns],
            "null_change": {c: {"a": int(da[c].isna().sum()), "b": int(db_[c].isna().sum())}
                            for c in common if da[c].isna().sum() != db_[c].isna().sum()},
            "dtype_change": {c: {"a": str(da[c].dtype), "b": str(db_[c].dtype)}
                             for c in common if str(da[c].dtype) != str(db_[c].dtype)}}


@router.get("/{ds_id}/lineage")
def lineage(ds_id: str, user=Depends(current_user)):
    """DAG: file -> versions (cleaning steps) -> saved queries -> dashboards."""
    import re
    d = ds.get_dataset(user["_id"], ds_id)
    nodes, edges = [], []
    layer_of = {}
    for v in d["versions"]:
        step = v["step"]
        label = d["name"] if step["op"] == "upload" else step["op"].replace("_", " ")
        nid = f"v{v['v']}"
        layer = 0 if v["parent"] is None else layer_of[f"v{v['parent']}"] + 1
        layer_of[nid] = layer
        nodes.append({"id": nid, "label": f"v{v['v']} · {label}", "kind": "file" if step["op"] == "upload" else "step",
                      "layer": layer, "sub": f"{v['rows']:,} rows"})
        if v["parent"] is not None:
            edges.append({"from": f"v{v['parent']}", "to": nid})
    top = max(layer_of.values()) + 1
    cur = f"v{d['current_version']}"
    pat = re.compile(rf"\b{re.escape(d['table'])}\b", re.I)
    qids = {}
    for q in queries.find({"owner": user["_id"]}):
        if pat.search(q["sql"]):
            qids[q["sql"]] = f"q{q['_id']}"
            nodes.append({"id": qids[q["sql"]], "label": q["name"], "kind": "query", "layer": top, "sub": "saved query"})
            edges.append({"from": cur, "to": qids[q["sql"]]})
    for dash in dashboards.find({"owner": user["_id"]}):
        hit = [w for w in dash["widgets"] if w["sql"] in qids or pat.search(w["sql"])]
        if hit:
            nodes.append({"id": f"d{dash['_id']}", "label": dash["name"], "kind": "dashboard", "layer": top + 1,
                          "sub": f"{len(hit)} chart(s)"})
            for w in hit:
                edges.append({"from": qids.get(w["sql"], cur), "to": f"d{dash['_id']}"})
    return {"nodes": nodes, "edges": edges}


@router.get("/{ds_id}/export")
def export_dataset_endpoint(ds_id: str, format: str = "xlsx", user=Depends(current_user)):
    from .pipeline import export_dataset
    return export_dataset(ds_id=ds_id, format=format, user=user)


@router.get("/{ds_id}/download")
def download_dataset(
    ds_id: str,
    format: str = "xlsx",
    version: int | None = None,
    include_change_log: bool = True,
    highlight_changes: bool = False,
    user=Depends(current_user),
):
    if format in ("xlsx", "csv"):
        return download_excel_workbook(
            ds_id=ds_id,
            format=format,
            include_change_log=include_change_log,
            highlight_changes=highlight_changes,
            user=user,
        )
    from .cleaning import download_cleaned_data
    return download_cleaned_data(ds_id=ds_id, format=format, version=version, user=user)



@router.get("/{ds_id}/report")
def get_report(ds_id: str, version: int | None = None, download: bool = False, user=Depends(current_user)):
    from .cleaning import get_cleaning_report
    return get_cleaning_report(ds_id=ds_id, version=version, download=download, user=user)


@router.get("/{ds_id}/log")
def get_log(ds_id: str, version: int | None = None, user=Depends(current_user)):
    from .cleaning import get_transformation_log
    return get_transformation_log(ds_id=ds_id, version=version, user=user)


class ColumnRulesBody(BaseModel):
    rules: dict[str, dict]


@router.get("/{ds_id}/column-rules")
def get_column_rules(ds_id: str, user=Depends(current_user)):
    """Retrieve detected semantics, missing-value policies, preview lines, and overrides."""
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}

    from ..services.column_semantics import infer_dataset_semantics
    from ..services.missing_policy import (
        POLICY_MATRIX,
        detect_derived_formulas,
        find_best_group_column,
        get_preview_line,
    )

    semantics = infer_dataset_semantics(df, overrides=overrides)
    formulas = detect_derived_formulas(df)
    formula_map = {f["target"]: f["expression"] for f in formulas}

    columns = []
    for c in df.columns:
        c_str = str(c)
        sem_info = semantics.get(c_str, {})
        sem_type = sem_info.get("semantic_type", "other_text")
        policy = POLICY_MATRIX.get(sem_type, POLICY_MATRIX["other_text"])
        saved = saved_rules.get(c_str, {})

        missing_rule = saved.get("missing_rule") or policy["default_missing_rule"]
        invalid_rule = saved.get("invalid_rule") or policy["default_invalid_rule"]
        null_count = int(df[c].isna().sum())
        group_col = find_best_group_column(df, c_str, semantics)
        formula_expr = formula_map.get(c_str)

        preview = get_preview_line(
            col=c_str,
            null_count=null_count,
            semantic_type=sem_type,
            missing_rule=missing_rule,
            group_col=group_col,
            formula_expr=formula_expr,
        )

        columns.append({
            "name": c_str,
            "semantic_type": sem_type,
            "confidence": sem_info.get("confidence", 0.5),
            "evidence": sem_info.get("evidence", ""),
            "needs_confirmation": sem_info.get("needs_confirmation", False),
            "is_override": sem_info.get("is_override", False),
            "missing_rule": missing_rule,
            "invalid_rule": invalid_rule,
            "allowed_missing_rules": policy["allowed_missing_rules"],
            "allowed_invalid_rules": policy["allowed_invalid_rules"],
            "null_count": null_count,
            "preview_line": preview,
            "detected_formula": formula_expr,
        })

    return {
        "columns": columns,
        "formulas": [{"target": f["target"], "expression": f["expression"], "confidence": f["confidence"]} for f in formulas],
    }


@router.post("/{ds_id}/column-rules")
def save_column_rules(ds_id: str, body: ColumnRulesBody, user=Depends(current_user)):
    """Save user overrides for column semantic types and cleaning policies."""
    d = ds.get_dataset(user["_id"], ds_id)
    datasets.update_one(
        {"_id": d["_id"]},
        {"$set": {
            "column_rules": body.rules,
            "source_meta.column_semantics": {c: {"semantic_type": r.get("semantic_type")} for c, r in body.rules.items() if r.get("semantic_type")},
        }}
    )
    return {"status": "ok", "saved_count": len(body.rules)}


# ────────────────────────────────────────────────────────────────────────────
# Interactive Editable Grid & Semantic Issue Fixing Endpoints
# ────────────────────────────────────────────────────────────────────────────
from typing import Any
import re
import datetime as dt
from fastapi.responses import StreamingResponse
import io
import urllib.parse
from ..services import grid_service
from ..services.column_semantics import infer_dataset_semantics


class FixRequest(BaseModel):
    issue_type: str
    column: str
    row: int | None = None
    strategy: str
    value: Any = None
    scope: str = "cell"  # "cell" | "column"


class CellEditItem(BaseModel):
    row: int
    column: str
    value: Any


class BatchCellsRequest(BaseModel):
    edits: list[CellEditItem]


class RevertCellRequest(BaseModel):
    row: int
    column: str


class ColumnActionRequest(BaseModel):
    column: str
    action: str  # "change_type", "trim", "change_case", "standardise", "fill_missing", "remove", "rename"
    params: dict[str, Any] = {}


def _format_cell_val(v: Any) -> Any:
    if v is None or pd.isna(v):
        return ""
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if np.isnan(v) or np.isinf(v):
            return ""
        return int(v) if float(v).is_integer() else float(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    try:
        f = float(s)
        return int(f) if f.is_integer() else round(f, 4)
    except Exception:
        return s


@router.get("/{ds_id}/grid")
def get_dataset_grid(
    ds_id: str,
    sheet: str | None = None,
    offset: int = 0,
    limit: int = 100,
    view: str = "cleaned",  # "cleaned" | "original" | "changes_only"
    search: str | None = None,
    sort_by: str | None = None,
    sort_asc: bool = True,
    issue_filter: str | None = None,
    column_filter: str | None = None,
    user=Depends(current_user),
):
    """
    Returns virtualizable, paged rows with cell values and rich issue metadata.
    Views:
      - 'cleaned': latest working copy
      - 'original': raw uploaded copy (v1)
      - 'changes_only': only rows where working copy differs from v1
    """
    d = ds.get_dataset(user["_id"], ds_id)
    raw_df = ds.load_df(d, 1)
    cur_df = ds.load_df(d)

    # Detect semantics
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)

    # Detect all issues on working copy
    issues_info = grid_service.detect_issues_for_dataset(cur_df, semantics=semantics, overrides=overrides)
    issue_cells = issues_info["cells"]
    dup_rows = issues_info["row_duplicates"]

    # Select base dataframe according to view
    if view == "original":
        display_df = raw_df.copy()
    else:
        display_df = cur_df.copy()

    # Search filter
    if search:
        s_lower = search.strip().lower()
        row_matches = display_df.astype(str).apply(lambda r: r.str.lower().str.contains(s_lower, regex=False).any(), axis=1)
        display_df = display_df[row_matches]

    # Changes only view
    if view == "changes_only":
        changed_indices = []
        for r_idx in display_df.index:
            if r_idx in raw_df.index:
                row_cur = cur_df.loc[r_idx]
                row_raw = raw_df.loc[r_idx]
                if not row_cur.equals(row_raw):
                    changed_indices.append(r_idx)
            else:
                changed_indices.append(r_idx)
        display_df = display_df.loc[changed_indices]

    # Issue filter (clicking chip like 'Missing', 'Outlier', etc.)
    if issue_filter:
        filtered_rows = set()
        for (r_idx, c_name), iss_list in issue_cells.items():
            if any(iss.get("type") == issue_filter for iss in iss_list):
                filtered_rows.add(r_idx)
        display_df = display_df.loc[[r for r in display_df.index if r in filtered_rows]]

    # Column filter
    if column_filter and column_filter in display_df.columns:
        col_issue_rows = {r for (r, c) in issue_cells.keys() if c == column_filter}
        display_df = display_df.loc[[r for r in display_df.index if r in col_issue_rows]]

    # Sorting
    if sort_by and sort_by in display_df.columns:
        display_df = display_df.sort_values(by=sort_by, ascending=sort_asc)

    total_filtered_rows = len(display_df)
    paged_df = display_df.iloc[offset: offset + limit]

    # Column metadata
    columns_meta = []
    for c in cur_df.columns:
        c_str = str(c)
        s_info = semantics.get(c_str, {})
        sem_t = s_info.get("semantic_type", "other_text")
        type_cat = grid_service._get_column_type_category(sem_t, cur_df[c].dtype)
        columns_meta.append({
            "name": c_str,
            "semantic_type": sem_t,
            "type_category": type_cat,
            "issue_count": issues_info["counts_by_column"].get(c_str, 0),
            "null_count": int(cur_df[c].isna().sum()),
        })

    # Build row cells with issues
    rows_data = []
    for r_idx in paged_df.index:
        r_int = int(r_idx)
        row_cur = paged_df.loc[r_idx]
        has_raw = r_idx in raw_df.index
        row_raw = raw_df.loc[r_idx] if has_raw else None

        cells_dict = {}
        for c in cur_df.columns:
            c_str = str(c)
            val = row_cur[c] if c in row_cur else None
            raw_val = row_raw[c] if (row_raw is not None and c in row_raw) else val

            # Check changed status
            val_clean = "" if (pd.isna(val) or val is None) else str(val)
            raw_clean = "" if (pd.isna(raw_val) or raw_val is None) else str(raw_val)
            is_changed = (val_clean != raw_clean)

            # Cell issues
            c_issues = issue_cells.get((r_int, c_str), [])
            issue_tags = []
            for iss in c_issues:
                t = iss.get("type", "missing")
                cfg = grid_service.ISSUE_CONFIG.get(t, grid_service.ISSUE_CONFIG["missing"])
                issue_tags.append({
                    "type": t,
                    "label": iss.get("label", cfg["label"]),
                    "message": iss.get("message", ""),
                    "color": cfg["color"],
                    "icon": cfg["icon"],
                    "badge_bg": cfg["badge_bg"],
                    "badge_text": cfg["badge_text"],
                    "border": cfg["border"],
                })

            cells_dict[c_str] = {
                "val": _format_cell_val(val),
                "raw_val": _format_cell_val(raw_val),
                "is_changed": is_changed,
                "issues": issue_tags,
                "has_issue": len(issue_tags) > 0,
            }

        rows_data.append({
            "_row_index": r_int,
            "_is_duplicate": r_int in dup_rows,
            "_has_issues": any(len(cells_dict[str(c)]["issues"]) > 0 for c in cur_df.columns),
            "_cells": cells_dict,
        })

    # Calculate version stack status
    cur_v = d.get("current_version", 1)
    max_v = max([x["v"] for x in d.get("versions", [{"v": 1}])])

    return {
        "total_rows": total_filtered_rows,
        "offset": offset,
        "limit": limit,
        "view": view,
        "columns": columns_meta,
        "rows": rows_data,
        "total_issues": issues_info["total_issues"],
        "counts_by_type": issues_info["counts_by_type"],
        "counts_by_column": issues_info["counts_by_column"],
        "current_version": cur_v,
        "max_version": max_v,
        "can_undo": cur_v > 1,
        "can_redo": d.get("redo_target") is not None,
    }


@router.get("/{ds_id}/issues")
def get_dataset_issues(ds_id: str, user=Depends(current_user)):
    """Return counts by type, counts by column, and ordered issues list for next/previous navigation."""
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d)
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)

    issues_info = grid_service.detect_issues_for_dataset(cur_df, semantics=semantics, overrides=overrides)
    raw_df = ds.load_df(d, 1)
    raw_issues = grid_service.detect_issues_for_dataset(raw_df, semantics=semantics)
    resolved_count = max(0, raw_issues["total_issues"] - issues_info["total_issues"])

    return {
        "total": issues_info["total_issues"],
        "counts_by_type": issues_info["counts_by_type"],
        "counts_by_column": issues_info["counts_by_column"],
        "ordered_issues": issues_info["ordered_issues"],
        "resolved_count": resolved_count,
        "initial_total": raw_issues["total_issues"],
    }


@router.get("/{ds_id}/suggest")
def get_issue_suggestion(
    ds_id: str,
    column: str,
    issue: str = "missing",
    row: int = 0,
    user=Depends(current_user),
):
    """
    Get suggestion for a cell problem. Adheres to strict semantic rules:
      - IDs, emails, phones, names, dates NEVER get mean/median/mode
      - Concise <= 6-words explanation
    """
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d)
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)

    if column not in cur_df.columns:
        raise HTTPException(400, f"Column '{column}' does not exist.")

    suggestion = grid_service.get_suggestion_for_cell(
        df=cur_df,
        col=column,
        row=row,
        issue_type=issue,
        semantics=semantics,
    )
    return suggestion


@router.post("/{ds_id}/fix")
def apply_fix_endpoint(
    ds_id: str,
    body: FixRequest,
    user=Depends(current_user),
):
    """Apply an issue fix to a single cell or across all matching cells in that column."""
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d)
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)

    try:
        new_df, affected_count, changes = grid_service.apply_cell_or_column_fix(
            df=cur_df,
            issue_type=body.issue_type,
            column=body.column,
            row=body.row,
            strategy=body.strategy,
            value=body.value,
            scope=body.scope,
            semantics=semantics,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Add version
    step_doc = {
        "op": "fix_issue",
        "params": {
            "issue_type": body.issue_type,
            "column": body.column,
            "row": body.row,
            "strategy": body.strategy,
            "value": str(body.value),
            "scope": body.scope,
            "affected_count": affected_count,
        },
    }
    new_v = ds.add_version(d, new_df, step_doc)

    # Append to edit log and reset redo stack
    datasets.update_one(
        {"_id": d["_id"]},
        {
            "$push": {"edit_log": {"$each": changes}},
            "$unset": {"redo_target": ""},
        },
    )

    return {
        "ok": True,
        "affected_count": affected_count,
        "version": new_v,
        "column": body.column,
        "strategy": body.strategy,
    }


@router.patch("/{ds_id}/cells")
def batch_update_cells(
    ds_id: str,
    body: BatchCellsRequest,
    user=Depends(current_user),
):
    """
    Validate and save batch manual edits (e.g. paste from Excel, fill down, direct cell editing).
    Invalid inputs fail validation and are rejected.
    """
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d).copy()
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)

    changes = []
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    # Validate all edits first
    for edit in body.edits:
        col = edit.column
        if col not in cur_df.columns:
            raise HTTPException(400, f"Column '{col}' does not exist.")
        if edit.row not in cur_df.index:
            raise HTTPException(400, f"Row {edit.row} does not exist.")

        sem_info = semantics.get(col, {})
        sem_t = sem_info.get("semantic_type", "other_text")

        is_valid, parsed_val, err_msg = grid_service.validate_cell_value(
            val_str=str(edit.value if edit.value is not None else ""),
            col=col,
            sem_type=sem_t,
            dtype=cur_df[col].dtype,
        )
        if not is_valid:
            raise HTTPException(400, f"Invalid value in row {edit.row}, column '{col}': {err_msg}")

    # Apply all valid edits
    for edit in body.edits:
        col = edit.column
        row = edit.row
        sem_info = semantics.get(col, {})
        sem_t = sem_info.get("semantic_type", "other_text")
        _, parsed_val, _ = grid_service.validate_cell_value(
            val_str=str(edit.value if edit.value is not None else ""),
            col=col,
            sem_type=sem_t,
            dtype=cur_df[col].dtype,
        )

        old_val = cur_df.at[row, col]
        try:
            cur_df.at[row, col] = parsed_val
        except Exception:
            cur_df[col] = cur_df[col].astype(object)
            cur_df.at[row, col] = parsed_val

        changes.append({
            "cell": f"{col}[{row}]",
            "row": row,
            "column": col,
            "old_val": None if pd.isna(old_val) else str(old_val),
            "new_val": str(parsed_val),
            "source": "manual",
            "time": now_iso,
        })

    # Save new version
    step_doc = {
        "op": "batch_cell_edit",
        "params": {"count": len(body.edits)},
    }
    new_v = ds.add_version(d, cur_df, step_doc)

    datasets.update_one(
        {"_id": d["_id"]},
        {
            "$push": {"edit_log": {"$each": changes}},
            "$unset": {"redo_target": ""},
        },
    )

    return {
        "ok": True,
        "updated_count": len(body.edits),
        "version": new_v,
    }


@router.post("/{ds_id}/undo")
def undo_action(ds_id: str, user=Depends(current_user)):
    """Undo the most recent action by reverting to parent version."""
    d = ds.get_dataset(user["_id"], ds_id)
    cur_v = d.get("current_version", 1)
    if cur_v <= 1:
        raise HTTPException(400, "Nothing to undo (already at original upload).")

    cur_entry = next((v for v in d["versions"] if v["v"] == cur_v), None)
    if not cur_entry or cur_entry.get("parent") is None:
        target_v = cur_v - 1
    else:
        target_v = cur_entry["parent"]

    datasets.update_one(
        {"_id": d["_id"]},
        {
            "$set": {
                "current_version": target_v,
                "redo_target": cur_v,
            }
        },
    )
    return {"ok": True, "current_version": target_v, "undone_version": cur_v}


@router.post("/{ds_id}/redo")
def redo_action(ds_id: str, user=Depends(current_user)):
    """Redo previously undone action."""
    d = ds.get_dataset(user["_id"], ds_id)
    redo_v = d.get("redo_target")
    if not redo_v or redo_v not in {v["v"] for v in d["versions"]}:
        raise HTTPException(400, "Nothing to redo.")

    datasets.update_one(
        {"_id": d["_id"]},
        {
            "$set": {"current_version": redo_v},
            "$unset": {"redo_target": ""},
        },
    )
    return {"ok": True, "current_version": redo_v}


@router.post("/{ds_id}/revert-cell")
def revert_cell_to_original(
    ds_id: str,
    body: RevertCellRequest,
    user=Depends(current_user),
):
    """Reverts a single cell back to its value from the original upload (v1)."""
    d = ds.get_dataset(user["_id"], ds_id)
    raw_df = ds.load_df(d, 1)
    cur_df = ds.load_df(d).copy()

    if body.column not in cur_df.columns:
        raise HTTPException(400, f"Column '{body.column}' does not exist.")
    if body.row not in cur_df.index:
        raise HTTPException(400, f"Row {body.row} does not exist.")

    raw_val = raw_df.at[body.row, body.column] if (body.row in raw_df.index and body.column in raw_df.columns) else ""
    old_val = cur_df.at[body.row, body.column]
    try:
        cur_df.at[body.row, body.column] = raw_val
    except Exception:
        cur_df[body.column] = cur_df[body.column].astype(object)
        cur_df.at[body.row, body.column] = raw_val

    step_doc = {
        "op": "revert_cell",
        "params": {"row": body.row, "column": body.column, "reverted_to": str(raw_val)},
    }
    new_v = ds.add_version(d, cur_df, step_doc)

    change = {
        "cell": f"{body.column}[{body.row}]",
        "row": body.row,
        "column": body.column,
        "old_val": None if pd.isna(old_val) else str(old_val),
        "new_val": None if pd.isna(raw_val) else str(raw_val),
        "source": "revert",
        "time": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    datasets.update_one(
        {"_id": d["_id"]},
        {
            "$push": {"edit_log": change},
            "$unset": {"redo_target": ""},
        },
    )

    return {
        "ok": True,
        "row": body.row,
        "column": body.column,
        "reverted_value": "" if pd.isna(raw_val) else raw_val,
        "version": new_v,
    }


@router.post("/{ds_id}/fix-all-suggested")
def fix_all_suggested_endpoint(ds_id: str, user=Depends(current_user)):
    """Toolbar button: applies high-confidence suggestions across the dataset."""
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d)
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)

    new_df, resolved_counts, changes, clean_check = grid_service.fix_all_high_confidence_suggested(
        cur_df,
        semantics=semantics,
    )
    total_resolved = sum(resolved_counts.values())

    step_doc = {
        "op": "fix_all_suggested",
        "params": {
            "resolved_counts": resolved_counts,
            "total_resolved": total_resolved,
            "clean_check": clean_check,
        },
    }
    new_v = ds.add_version(d, new_df, step_doc)

    datasets.update_one(
        {"_id": d["_id"]},
        {
            "$push": {"edit_log": {"$each": changes}},
            "$unset": {"redo_target": ""},
        },
    )

    return {
        "ok": True,
        "resolved_counts": resolved_counts,
        "total_resolved": total_resolved,
        "clean_check": clean_check,
        "version": new_v,
    }


@router.get("/{ds_id}/clean-check")
def get_clean_check_endpoint(ds_id: str, user=Depends(current_user)):
    """Runs a full clean check on the dataset version asserting 0 auto-fixable issues remain."""
    from ..services.complete_cleaner import run_clean_check
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d)
    saved_rules = d.get("column_rules", {})
    overrides = {c: r["semantic_type"] for c, r in saved_rules.items() if r.get("semantic_type")}
    semantics = infer_dataset_semantics(cur_df, overrides=overrides)
    return run_clean_check(cur_df, semantics=semantics)


@router.post("/{ds_id}/column-action")
def column_action_endpoint(
    ds_id: str,
    body: ColumnActionRequest,
    user=Depends(current_user),
):
    """Header actions: Change type, Trim, Change case, Standardise values, Fill missing, Remove column, Rename."""
    d = ds.get_dataset(user["_id"], ds_id)
    cur_df = ds.load_df(d).copy()
    col = body.column
    if col not in cur_df.columns:
        raise HTTPException(400, f"Column '{col}' does not exist.")

    action = body.action
    params = body.params
    changes = []
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    if action == "trim":
        cur_df[col] = cur_df[col].astype(str).str.strip()
    elif action == "change_case":
        case_type = params.get("case", "upper")
        if case_type == "upper":
            cur_df[col] = cur_df[col].astype(str).str.upper()
        elif case_type == "lower":
            cur_df[col] = cur_df[col].astype(str).str.lower()
        elif case_type == "title":
            cur_df[col] = cur_df[col].astype(str).str.title()
    elif action == "standardise":
        s = cur_df[col]
        counts = {}
        canonical = {}
        for v in s.dropna():
            sv = str(v).strip()
            counts[sv] = counts.get(sv, 0) + 1
            low = sv.lower()
            if low not in canonical or counts[sv] > counts.get(canonical[low], 0):
                canonical[low] = sv
        cur_df[col] = cur_df[col].apply(lambda x: canonical.get(str(x).strip().lower(), x) if pd.notna(x) else x)
    elif action == "remove":
        cur_df = cur_df.drop(columns=[col])
    elif action == "rename":
        new_name = str(params.get("new_name", "")).strip()
        if not new_name:
            raise HTTPException(400, "New column name cannot be empty.")
        cur_df = cur_df.rename(columns={col: new_name})
    elif action == "change_type":
        target_t = params.get("target_type", "text")
        if target_t == "number":
            cur_df[col] = pd.to_numeric(cur_df[col], errors="coerce")
        elif target_t == "date":
            cur_df[col] = pd.to_datetime(cur_df[col], errors="coerce")
        elif target_t == "text":
            cur_df[col] = cur_df[col].astype(str)
    else:
        raise HTTPException(400, f"Unsupported action '{action}'.")

    step_doc = {"op": f"column_{action}", "params": {"column": col, **params}}
    new_v = ds.add_version(d, cur_df, step_doc)

    return {"ok": True, "action": action, "column": col, "version": new_v}


@router.get("/{ds_id}/download-excel")
def download_excel_workbook(
    ds_id: str,
    format: str = "xlsx",
    include_change_log: bool = True,
    highlight_changes: bool = False,
    user=Depends(current_user),
):
    """
    Download Excel workbook containing:
      Tab 1: Raw_Data (raw upload copy)
      Tab 2: Processed_Data (cleaned, typed cells, frozen header, autofilter)
      Optional Tab 3: Change_Log
      Optional Tab 4: Needs_Review
    Or CSV of processed data.
    """
    d = ds.get_dataset(user["_id"], ds_id)
    raw_df = ds.load_df(d, 1)
    cur_df = ds.load_df(d)

    edit_log = d.get("edit_log", [])
    base_name = re.sub(r"\.[^.]+$", "", d["name"])
    clean_filename = f"{base_name}_cleaned.{format}"

    if format == "csv":
        csv_buf = io.StringIO()
        cur_df.to_csv(csv_buf, index=False)
        return StreamingResponse(
            io.BytesIO(csv_buf.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{clean_filename}"'},
        )

    # XLSX format
    xlsx_bytes = grid_service.build_raw_and_processed_workbook(
        raw_df=raw_df,
        processed_df=cur_df,
        edit_log=edit_log,
        include_change_log=include_change_log,
        highlight_changes=highlight_changes,
        sheet_name="Data",
    )

    encoded_name = urllib.parse.quote(clean_filename)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{id}/dashboard-data")
def get_dataset_dashboard_data(
    id: str,
    date_min: str | None = None,
    date_max: str | None = None,
    date_grain: str | None = None,
    cat1_col: str | None = None,
    cat1_vals: str | None = None,
    cat2_col: str | None = None,
    cat2_vals: str | None = None,
    cat3_col: str | None = None,
    cat3_vals: str | None = None,
    cross_dim: str | None = None,
    cross_val: str | None = None,
    user=Depends(current_user),
):
    """
    Returns computed KPIs, suitable charts, auto-filters, and 5-8 consolidated key insights
    from the single shared calculation layer (Power BI / Tableau Inspired).
    """
    from ..services.dashboard_engine import get_dashboard_payload

    d = ds.get_dataset(user["_id"], id)
    raw_df = ds.load_df(d, 1)
    cur_ver = d.get("current_version", 1)
    try:
        cur_df = ds.load_df(d, cur_ver)
    except Exception:
        cur_df = raw_df.copy()

    # Build active filters dict
    filters = {}
    if date_min or date_max:
        # Find date column if not passed
        date_cols = [c for c in cur_df.columns if pd.api.types.is_datetime64_any_dtype(cur_df[c])]
        if not date_cols:
            for c in cur_df.columns:
                if any(w in str(c).lower() for w in ("date", "time", "dob", "period")):
                    date_cols.append(c)
                    break
        if date_cols:
            filters["date_col"] = date_cols[0]
            if date_min:
                filters["date_min"] = date_min
            if date_max:
                filters["date_max"] = date_max

    if date_grain:
        filters["date_grain"] = date_grain

    categories_filter = {}
    if cat1_col and cat1_vals:
        categories_filter[cat1_col] = [v.strip() for v in cat1_vals.split(",") if v.strip()]
    if cat2_col and cat2_vals:
        categories_filter[cat2_col] = [v.strip() for v in cat2_vals.split(",") if v.strip()]
    if cat3_col and cat3_vals:
        categories_filter[cat3_col] = [v.strip() for v in cat3_vals.split(",") if v.strip()]
    if categories_filter:
        filters["categories"] = categories_filter

    if cross_dim and cross_val:
        filters["cross_dim"] = cross_dim
        filters["cross_val"] = cross_val

    meta = {
        "column_semantics": d.get("column_semantics", {}),
        "column_currencies": d.get("column_currencies", {}),
    }

    payload = get_dashboard_payload(
        df_raw=cur_df,
        dataset_name=d.get("name", "Dataset"),
        dataset_id=id,
        source_meta=meta,
        filters=filters,
    )
    return payload


@router.get("/{id}/download-report")
def download_executive_pdf_report(
    id: str,
    date_min: str | None = None,
    date_max: str | None = None,
    cat1_col: str | None = None,
    cat1_vals: str | None = None,
    cat2_col: str | None = None,
    cat2_vals: str | None = None,
    user=Depends(current_user),
):
    """
    Downloads executive PDF report containing KPIs, consolidated key insights, and visual summaries.
    """
    from ..services.dashboard_engine import generate_executive_pdf_report

    d = ds.get_dataset(user["_id"], id)
    raw_df = ds.load_df(d, 1)
    cur_ver = d.get("current_version", 1)
    try:
        cur_df = ds.load_df(d, cur_ver)
    except Exception:
        cur_df = raw_df.copy()

    filters = {}
    if date_min or date_max:
        date_cols = [c for c in cur_df.columns if pd.api.types.is_datetime64_any_dtype(cur_df[c])]
        if not date_cols:
            for c in cur_df.columns:
                if any(w in str(c).lower() for w in ("date", "time", "dob", "period")):
                    date_cols.append(c)
                    break
        if date_cols:
            filters["date_col"] = date_cols[0]
            if date_min:
                filters["date_min"] = date_min
            if date_max:
                filters["date_max"] = date_max

    categories_filter = {}
    if cat1_col and cat1_vals:
        categories_filter[cat1_col] = [v.strip() for v in cat1_vals.split(",") if v.strip()]
    if cat2_col and cat2_vals:
        categories_filter[cat2_col] = [v.strip() for v in cat2_vals.split(",") if v.strip()]
    if categories_filter:
        filters["categories"] = categories_filter

    meta = {
        "column_semantics": d.get("column_semantics", {}),
        "column_currencies": d.get("column_currencies", {}),
    }

    ds_name = d.get("name", "dataset")
    base_name = re.sub(r"\.[^.]+$", "", ds_name)
    pdf_filename = f"{base_name}_executive_report.pdf"

    pdf_bytes = generate_executive_pdf_report(
        df_raw=cur_df,
        dataset_name=base_name,
        source_meta=meta,
        filters=filters,
    )

    encoded_name = urllib.parse.quote(pdf_filename)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )




