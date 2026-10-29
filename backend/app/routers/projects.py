"""API router for Requirements Workspace (Projects)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import current_user
from ..services import datasets as ds_svc
from ..services import projects as proj_svc

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str
    business_question: str = ""
    stakeholders: list[dict] = []
    success_metrics: list[str] = []
    required_sources: list[str] = []
    deadline: str | None = None
    status: str = "draft"
    assumptions: list[str] = []
    risks: list[str] = []
    deliverables: list[dict] = []
    analysis_plan: dict | None = None
    linked_sources: list[str] = []
    linked_models: list[str] = []
    linked_pipelines: list[str] = []
    linked_dashboards: list[str] = []
    linked_reports: list[str] = []


class ProjectUpdateIn(BaseModel):
    name: str | None = None
    business_question: str | None = None
    stakeholders: list[dict] | None = None
    success_metrics: list[str] | None = None
    required_sources: list[str] | None = None
    deadline: str | None = None
    status: str | None = None
    assumptions: list[str] | None = None
    risks: list[str] | None = None
    deliverables: list[dict] | None = None
    analysis_plan: dict | None = None
    linked_sources: list[str] | None = None
    linked_models: list[str] | None = None
    linked_pipelines: list[str] | None = None
    linked_dashboards: list[str] | None = None
    linked_reports: list[str] | None = None
    workflow_state: dict | None = None


class DatasetLinkIn(BaseModel):
    dataset_id: str
    version: int = 1


class AnalysisPlanIn(BaseModel):
    business_question: str
    dataset_id: str | None = None


class ActivityIn(BaseModel):
    action: str
    details: str


@router.get("")
def list_projects(user=Depends(current_user)):
    return proj_svc.list_projects(user["_id"])


@router.get("/active")
def get_active_project(user=Depends(current_user)):
    return proj_svc.get_active_project(user["_id"])


@router.post("")
def create_project(body: ProjectIn, user=Depends(current_user)):
    try:
        return proj_svc.create_project(user["_id"], body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}")
def get_project(project_id: str, user=Depends(current_user)):
    try:
        return proj_svc.get_project(user["_id"], project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/{project_id}")
def update_project(project_id: str, body: ProjectUpdateIn, user=Depends(current_user)):
    try:
        updates = body.model_dump(exclude_unset=True)
        return proj_svc.update_project(user["_id"], project_id, updates)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{project_id}")
def delete_project(project_id: str, user=Depends(current_user)):
    try:
        proj_svc.delete_project(user["_id"], project_id)
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{project_id}/activate")
def activate_project(project_id: str, user=Depends(current_user)):
    try:
        return proj_svc.set_active_project(user["_id"], project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{project_id}/dataset")
def link_dataset(project_id: str, body: DatasetLinkIn, user=Depends(current_user)):
    try:
        return proj_svc.set_project_dataset(user["_id"], project_id, body.dataset_id, body.version)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/activity")
def add_activity(project_id: str, body: ActivityIn, user=Depends(current_user)):
    try:
        proj_svc.add_activity(user["_id"], project_id, body.action, body.details)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/generate-plan")
def generate_analysis_plan(body: AnalysisPlanIn, user=Depends(current_user)):
    try:
        columns = []
        semantics = None
        if body.dataset_id:
            meta = ds_svc.get_meta(user["_id"], body.dataset_id)
            profile = meta.get("profile", {})
            columns = profile.get("columns", [])
            semantics = profile.get("semantics")
        return proj_svc.generate_analysis_plan(body.business_question, columns, semantics)
    except Exception as e:
        raise HTTPException(400, str(e))
