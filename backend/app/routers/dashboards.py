import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import current_user
from ..db import dashboards
from ..gating import require_dataset
from ..services import auto_insights, charts, report, sql_engine
from ..services import datasets as ds
from ..services.profiling import profile
from .insights import verified_narrative

router = APIRouter(tags=["dashboards"])


class Widget(BaseModel):
    title: str
    sql: str | None = ""
    chart: str = "bar"
    x: str | None = None
    y: str | None = None
    color: str | None = None
    spec: dict | None = None


class AddWidget(BaseModel):
    dashboard_name: str
    widget: Widget


def _get(user, did):
    d = dashboards.find_one({"_id": did, "owner": user["_id"]})
    if not d:
        raise HTTPException(404, "Dashboard not found")
    return d


@router.get("/dashboards")
def list_(user=Depends(current_user)):
    return [{"id": d["_id"], "name": d["name"], "widgets": len(d["widgets"])} for d in dashboards.find({"owner": user["_id"]})]


@router.post("/dashboards/add-widget")
def add_widget(b: AddWidget, user=Depends(current_user)):
    d = dashboards.find_one({"owner": user["_id"], "name": b.dashboard_name})
    if not d:
        did = uuid.uuid4().hex[:10]
        dashboards.insert_one({"_id": did, "owner": user["_id"], "name": b.dashboard_name, "widgets": [b.widget.model_dump()]})
    else:
        did = d["_id"]
        dashboards.update_one({"_id": did}, {"$push": {"widgets": b.widget.model_dump()}})
    return {"id": did}


@router.delete("/dashboards/{did}")
def delete(did: str, user=Depends(current_user)):
    dashboards.delete_one({"_id": did, "owner": user["_id"]})
    return {"deleted": did}


def render_widgets(owner, widgets):
    out = []
    for w in widgets:
        try:
            sql = w.get("sql")
            opts = {}
            if w.get("spec"):
                from ..services.visual_compiler import VisualSpec, compile_visual_to_sql
                v_spec = VisualSpec(**w["spec"])
                d = ds.get_dataset(owner, v_spec.dataset_id)
                sql = compile_visual_to_sql(d["table"], v_spec)
                opts = v_spec.options or {}
            df, _ = sql_engine.run_df(owner, sql, max_rows=5000)
            fig = charts.make_figure(df, w.get("chart") or "bar", w.get("x"), w.get("y"), w.get("color"), w.get("title"), options=opts)
            out.append({"title": w["title"], "figure": fig, "spec": w.get("spec"), "error": None})
        except Exception as e:
            out.append({"title": w.get("title", "Widget"), "figure": None, "spec": w.get("spec"), "error": str(e)})
    return out


@router.get("/dashboards/{did}/render")
def render(did: str, user=Depends(current_user)):
    require_dataset(user)
    d = _get(user, did)
    return {"name": d["name"], "widgets": render_widgets(user["_id"], d["widgets"])}


@router.get("/dashboards/{did}/export-excel")
def export_dashboard_excel_endpoint(did: str, user=Depends(current_user)):
    require_dataset(user)
    d = _get(user, did)
    specs = [w["spec"] for w in d.get("widgets", []) if w.get("spec")]
    from .visuals import export_dashboard_excel, ExportExcelRequest
    req = ExportExcelRequest(
        dataset_id=specs[0]["dataset_id"] if specs else "",
        dashboard_name=d["name"],
        specs=specs,
    )
    return export_dashboard_excel(req, user=user)


class ReportIn(BaseModel):
    dataset_id: str
    title: str = "DataPilot Insight Report"
    dashboard_id: str | None = None


@router.post("/reports/generate")
def generate_report(b: ReportIn, user=Depends(current_user)):
    require_dataset(user)
    d = ds.get_dataset(user["_id"], b.dataset_id)
    df = ds.load_df(d)
    insights = auto_insights.generate(df, d["table"])
    narrative, by = verified_narrative(insights)
    figs = []
    if b.dashboard_id:
        figs = [{"title": w.get("title", ""), "figure": w["figure"]} for w in render_widgets(user["_id"], _get(user, b.dashboard_id)["widgets"]) if w["figure"]]
    html = report.build_html(b.title, d["name"], profile(df), insights, narrative, by, figs)
    return Response(html, media_type="text/html",
                    headers={"Content-Disposition": 'attachment; filename="datapilot_report.html"'})
