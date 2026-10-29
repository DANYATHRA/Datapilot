"""API router for domain KPI catalogue."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import current_user
from ..services import datasets as ds_svc
from ..services import kpi_catalogue as kpi_svc

router = APIRouter(prefix="/kpis", tags=["kpis"])


class RoleMappingIn(BaseModel):
    domain: str
    role_assignments: dict[str, str]


@router.get("/domains")
def list_domains():
    return list(kpi_svc.KPI_CATALOGUE.keys())


@router.get("/catalog/{domain}")
def get_domain_catalog(domain: str):
    kpis = kpi_svc.KPI_CATALOGUE.get(domain)
    if not kpis:
        raise HTTPException(404, f"Domain '{domain}' not found")
    return kpis


@router.get("/detect/{dataset_id}")
def detect_domain_and_roles(dataset_id: str, user=Depends(current_user)):
    try:
        df = ds_svc.load(user["_id"], dataset_id)
        meta = ds_svc.get_meta(user["_id"], dataset_id)
        semantics = meta.get("profile", {}).get("semantics")
        domain, role_assignments = kpi_svc.detect_domain_and_roles(df, semantics)
        available_kpis = kpi_svc.get_available_kpis(domain, role_assignments)
        return {
            "detected_domain": domain,
            "role_assignments": role_assignments,
            "kpis": available_kpis,
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/compute/{dataset_id}")
def compute_kpis(dataset_id: str, body: RoleMappingIn, user=Depends(current_user)):
    try:
        df = ds_svc.load(user["_id"], dataset_id)
        kpis = kpi_svc.get_available_kpis(body.domain, body.role_assignments)
        computed = []
        for k in kpis:
            val = kpi_svc.compute_kpi(df, k, body.role_assignments)
            if val:
                computed.append(val)
        return {"domain": body.domain, "computed": computed, "all_kpis": kpis}
    except Exception as e:
        raise HTTPException(400, str(e))
