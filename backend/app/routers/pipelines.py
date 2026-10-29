"""API router for visual ETL pipelines."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..auth import current_user
from ..services import pipeline_engine as pe_svc

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class PipelineIn(BaseModel):
    name: str
    description: str = ""
    steps: list[dict] = []
    parameters: list[dict] = []
    schedule: str | None = None


class RunIn(BaseModel):
    parameters: dict = {}


@router.get("")
def list_pipelines(user=Depends(current_user)):
    return pe_svc.list_pipelines(user["_id"])


@router.post("")
def create_pipeline(body: PipelineIn, user=Depends(current_user)):
    try:
        return pe_svc.create_pipeline(user["_id"], body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: str, user=Depends(current_user)):
    try:
        return pe_svc.get_pipeline(user["_id"], pipeline_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/{pipeline_id}")
def update_pipeline(pipeline_id: str, body: PipelineIn, user=Depends(current_user)):
    try:
        return pe_svc.update_pipeline(user["_id"], pipeline_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{pipeline_id}")
def delete_pipeline(pipeline_id: str, user=Depends(current_user)):
    try:
        pe_svc.delete_pipeline(user["_id"], pipeline_id)
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{pipeline_id}/run")
def execute_pipeline(pipeline_id: str, body: RunIn = RunIn(), user=Depends(current_user)):
    try:
        return pe_svc.run_pipeline(user["_id"], pipeline_id, params=body.parameters)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/{pipeline_id}/runs")
def list_runs(pipeline_id: str, limit: int = 20, user=Depends(current_user)):
    return pe_svc.get_run_history(user["_id"], pipeline_id, limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str, user=Depends(current_user)):
    try:
        return pe_svc.get_run(user["_id"], run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{pipeline_id}/code/{lang}")
def export_pipeline_code(pipeline_id: str, lang: str, user=Depends(current_user)):
    try:
        pipeline = pe_svc.get_pipeline(user["_id"], pipeline_id)
        lang_lower = lang.lower()
        if lang_lower in ("python", "py", "pandas"):
            code = pe_svc.export_as_python(pipeline)
            media_type = "text/x-python"
        elif lang_lower in ("sql",):
            code = pe_svc.export_as_sql(pipeline)
            media_type = "text/x-sql"
        elif lang_lower in ("r", "tidyverse"):
            code = pe_svc.export_as_r(pipeline)
            media_type = "text/x-r"
        else:
            raise HTTPException(400, f"Unsupported language: {lang}. Choose python, sql, or r.")
        return PlainTextResponse(code, media_type=media_type)
    except ValueError as e:
        raise HTTPException(404, str(e))
