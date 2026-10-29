"""
Router for the auto-clean pipeline.

  POST /pipeline/{ds_id}/run             → run all stages
  POST /pipeline/{ds_id}/run?dry_run=true → preview only
  GET  /pipeline/{ds_id}/report          → per-stage counts + sample changes
  GET  /pipeline/legend                  → colour legend
  GET  /datasets/{ds_id}/export          → colour-coded Excel workbook
"""
from __future__ import annotations

import io
import urllib.parse
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import current_user
from ..db import datasets as datasets_col
from ..services import datasets as ds
from ..services.pipeline import (
    STAGE_ORDER,
    build_export_workbook,
    get_legend,
    run_pipeline,
)

router = APIRouter(tags=["pipeline"])


# ── Models ──────────────────────────────────────────────────────────────────
class PipelineRunBody(BaseModel):
    skip: list[str] = []
    column_rules: dict[str, dict] | None = None


# ── Legend ──────────────────────────────────────────────────────────────────
@router.get("/pipeline/legend")
def legend():
    """Return the colour legend used by the pipeline."""
    return get_legend()


# ── Run pipeline ────────────────────────────────────────────────────────────
@router.post("/datasets/{ds_id}/pipeline/run")
def pipeline_run(
    ds_id: str,
    body: PipelineRunBody | None = None,
    dry_run: bool = Query(False),
    user=Depends(current_user),
):
    """
    Run the full 10-stage cleaning pipeline with Column-Aware Semantic Cleaning.

    - ``dry_run=true`` returns a stage-by-stage summary without saving.
    - ``body.skip`` is a list of stage keys to skip (e.g. ["outliers", "pii"]).
    - ``body.column_rules`` optional overrides per column.
    """
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)  # current version
    skip = (body.skip if body else [])
    col_rules = (body.column_rules if body and body.column_rules else None) or d.get("column_rules")

    # Validate skip list
    bad = [s for s in skip if s not in STAGE_ORDER]
    if bad:
        raise HTTPException(400, f"Unknown stage(s) to skip: {bad}. Valid: {STAGE_ORDER}")

    try:
        result = run_pipeline(
            df,
            sheet_name=d.get("name", "Sheet1"),
            skip=skip,
            column_rules=col_rules,
        )
    except Exception as e:
        raise HTTPException(400, f"Pipeline failed: {e}")

    cleaned_df = result["cleaned_df"]
    all_changes = result["all_changes"]
    removed_rows = result["removed_rows"]
    stage_summaries = result["stage_summaries"]
    quality_comparison = result["quality_comparison"]

    summary = {
        "stages": stage_summaries,
        "total_changes": len(all_changes),
        "removed_rows_count": len(removed_rows),
        "quality_before": quality_comparison.get("before") if quality_comparison else None,
        "quality_after": quality_comparison.get("after") if quality_comparison else None,
        "rows_before": len(df),
        "rows_after": len(cleaned_df),
    }

    if dry_run:
        # Return summary + sample changes per stage without saving
        sample_changes: dict[str, list[dict]] = {}
        for ch in all_changes:
            stg = ch["stage"]
            if stg not in sample_changes:
                sample_changes[stg] = []
            if len(sample_changes[stg]) < 5:
                sample_changes[stg].append(ch)

        return {
            "dry_run": True,
            "summary": summary,
            "sample_changes": sample_changes,
        }

    # Save — create one version per stage (for rollback audit trail)
    current_doc = d
    current_df = df

    for ss in stage_summaries:
        if ss["status"] == "skipped":
            continue

        stage_key = ss["stage"]
        # Re-run this single stage to get the intermediate DataFrame
        from ..services.pipeline import STAGE_FUNCTIONS, stage_validation
        if stage_key == "validation":
            # Validation doesn't change data, just compute
            continue

        fn = STAGE_FUNCTIONS[stage_key]
        current_df, _ = fn(current_df, d.get("name", "Sheet1"))

        step_doc = {
            "op": f"pipeline_{stage_key}",
            "params": {"pipeline_stage": stage_key, "changes": ss["changes"]},
        }
        new_v = ds.add_version(current_doc, current_df, step_doc)
        # Re-fetch to get updated doc with new version
        current_doc = ds.get_dataset(user["_id"], ds_id)

    # Store pipeline results metadata & detected column currencies & semantics
    datasets_col.update_one(
        {"_id": ds_id},
        {"$set": {
            "source_meta.column_currencies": result.get("column_currencies", {}),
            "column_currencies": result.get("column_currencies", {}),
            "source_meta.column_semantics": result.get("semantics", {}),
            "pipeline_result": {
                "stage_summaries": stage_summaries,
                "quality_comparison": quality_comparison,
                "total_changes": len(all_changes),
                "removed_rows_count": len(removed_rows),
                "review_count": len(result.get("needs_review_items", [])),
                "needs_review_items": result.get("needs_review_items", [])[:1000],
                "left_blank_by_design": result.get("left_blank_by_design", {}),
                "all_changes": all_changes[:1000],  # cap stored changes
                "removed_rows": removed_rows[:500],
            }
        }}
    )

    return {
        "dry_run": False,
        "version": current_doc["current_version"],
        "summary": summary,
        "all_changes": all_changes,
        "removed_rows": removed_rows,
    }


# ── Pipeline report ─────────────────────────────────────────────────────────
@router.get("/datasets/{ds_id}/pipeline/report")
def pipeline_report(ds_id: str, user=Depends(current_user)):
    """Per-stage counts + sample changes from the last pipeline run."""
    d = ds.get_dataset(user["_id"], ds_id)
    pr = d.get("pipeline_result")
    if not pr:
        raise HTTPException(404, "No pipeline has been run on this dataset yet.")

    sample_changes: dict[str, list[dict]] = {}
    for ch in pr.get("all_changes", []):
        stg = ch["stage"]
        if stg not in sample_changes:
            sample_changes[stg] = []
        if len(sample_changes[stg]) < 10:
            sample_changes[stg].append(ch)

    return {
        "stage_summaries": pr.get("stage_summaries", []),
        "quality_comparison": pr.get("quality_comparison"),
        "total_changes": pr.get("total_changes", 0),
        "removed_rows_count": pr.get("removed_rows_count", 0),
        "sample_changes": sample_changes,
    }


# ── Export colour-coded Excel ────────────────────────────────────────────────
@router.get("/datasets/{ds_id}/export")
@router.get("/datasets/{ds_id}/pipeline/export")
def export_dataset(
    ds_id: str,
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    user=Depends(current_user),
):
    """
    Export the cleaned dataset.

    - ``format=xlsx`` → multi-sheet workbook with highlights, change log, etc.
    - ``format=csv``  → CSV of Cleaned_Data only.
    """
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)

    base_name = d["name"]
    for ext in [".csv", ".xlsx", ".xls", ".json", ".parquet", ".txt"]:
        if base_name.lower().endswith(ext):
            base_name = base_name[: -len(ext)]
            break

    if format == "csv":
        buf = io.BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8")
        buf.seek(0)
        filename = f"{base_name}_cleaned.csv"
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )

    # XLSX — build colour-coded workbook
    pr = d.get("pipeline_result", {})
    all_changes = pr.get("all_changes", [])
    removed_rows = pr.get("removed_rows", [])
    stage_summaries = pr.get("stage_summaries", [])
    quality_comparison = pr.get("quality_comparison", {})
    needs_review_items = pr.get("needs_review_items", [])
    left_blank_by_design = pr.get("left_blank_by_design", [])
    raw_df = None
    try:
        raw_df = ds.load_df(d, 1)
    except Exception:
        pass

    xlsx_bytes = build_export_workbook(
        cleaned_df=df,
        all_changes=all_changes,
        removed_rows=removed_rows,
        stage_summaries=stage_summaries,
        quality_comparison=quality_comparison,
        needs_review_items=needs_review_items,
        left_blank_by_design=left_blank_by_design,
        sheet_name=d.get("name", "Sheet1"),
        raw_df=raw_df,
    )

    filename = f"{base_name}_cleaned.xlsx"
    quoted = urllib.parse.quote(filename)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quoted}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
