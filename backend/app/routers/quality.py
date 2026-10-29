"""API router for data quality scorecard."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..auth import current_user
from ..services import datasets as ds_svc
from ..services import quality as q_svc
from ..services.profiling import profile

import io

router = APIRouter(prefix="/quality", tags=["quality"])


class RuleIn(BaseModel):
    type: str
    column: str = ""
    name: str = ""
    severity: str = "warning"
    params: dict = {}
    enabled: bool = True


class RulesBody(BaseModel):
    rules: list[RuleIn]


@router.get("/{ds_id}/scorecard")
def get_scorecard(ds_id: str, user=Depends(current_user)):
    """Compute the full quality scorecard for a dataset."""
    d = ds_svc.get_dataset(user["_id"], ds_id)
    df = ds_svc.load_df(d)
    rules = q_svc.get_rules(user["_id"], ds_id)
    if not rules:
        rules = q_svc.suggest_rules(df)
    scorecard = q_svc.compute_quality_score(df, rules)
    return scorecard


@router.get("/{ds_id}/suggest-rules")
def suggest_rules(ds_id: str, user=Depends(current_user)):
    """Auto-suggest quality rules based on column semantics."""
    d = ds_svc.get_dataset(user["_id"], ds_id)
    df = ds_svc.load_df(d)
    from ..services.column_semantics import infer_dataset_semantics
    semantics = infer_dataset_semantics(df)
    suggested = q_svc.suggest_rules(df, semantics)
    return {"rules": suggested}


@router.post("/{ds_id}/rules")
def save_rules(ds_id: str, body: RulesBody, user=Depends(current_user)):
    """Save quality rules for a dataset."""
    rules = [r.model_dump() for r in body.rules]
    saved = q_svc.save_rules(user["_id"], ds_id, rules)
    return {"saved": len(saved), "rules": saved}


@router.get("/{ds_id}/rules")
def get_rules(ds_id: str, user=Depends(current_user)):
    """Get all quality rules for a dataset."""
    rules = q_svc.get_rules(user["_id"], ds_id)
    return {"rules": rules}


@router.delete("/{ds_id}/rules/{rule_id}")
def delete_rule(ds_id: str, rule_id: str, user=Depends(current_user)):
    q_svc.delete_rule(user["_id"], rule_id)
    return {"deleted": rule_id}


@router.post("/{ds_id}/evaluate")
def evaluate_rules(ds_id: str, body: RulesBody | None = None, user=Depends(current_user)):
    """Evaluate rules against the dataset and return full scorecard."""
    d = ds_svc.get_dataset(user["_id"], ds_id)
    df = ds_svc.load_df(d)
    if body and body.rules:
        rules = [r.model_dump() for r in body.rules]
    else:
        rules = q_svc.get_rules(user["_id"], ds_id)
        if not rules:
            rules = q_svc.suggest_rules(df)
    scorecard = q_svc.compute_quality_score(df, rules)
    return scorecard


@router.get("/{ds_id}/report/html")
def quality_report_html(ds_id: str, user=Depends(current_user)):
    """Export quality report as HTML."""
    d = ds_svc.get_dataset(user["_id"], ds_id)
    df = ds_svc.load_df(d)
    rules = q_svc.get_rules(user["_id"], ds_id)
    if not rules:
        rules = q_svc.suggest_rules(df)
    scorecard = q_svc.compute_quality_score(df, rules)
    html = q_svc.quality_report_html(scorecard, d["name"])
    return HTMLResponse(content=html)


@router.get("/{ds_id}/report/excel")
def quality_report_excel(ds_id: str, user=Depends(current_user)):
    """Export quality report as Excel."""
    import pandas as pd

    d = ds_svc.get_dataset(user["_id"], ds_id)
    df = ds_svc.load_df(d)
    rules = q_svc.get_rules(user["_id"], ds_id)
    if not rules:
        rules = q_svc.suggest_rules(df)
    scorecard = q_svc.compute_quality_score(df, rules)

    # Build Excel with multiple sheets
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # Summary sheet
        summary = pd.DataFrame([{
            "Dimension": dim.title(),
            "Score": info["score"],
        } for dim, info in scorecard["dimensions"].items()])
        summary.to_excel(writer, sheet_name="Summary", index=False)

        # Issues sheet
        if scorecard.get("issue_log"):
            issues_df = pd.DataFrame(scorecard["issue_log"])
            issues_df = issues_df.drop(columns=["sample_rows"], errors="ignore")
            issues_df.to_excel(writer, sheet_name="Issues", index=False)

        # Rule results sheet
        if scorecard.get("rule_results"):
            rules_df = pd.DataFrame([{
                "Rule": r["rule_name"], "Column": r["column"],
                "Passed": r["passed"], "Failures": r["fail_count"],
                "Fail %": r["fail_pct"], "Fix": r["suggested_fix"],
            } for r in scorecard["rule_results"]])
            rules_df.to_excel(writer, sheet_name="Rules", index=False)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="quality_report_{ds_id}.xlsx"'},
    )
