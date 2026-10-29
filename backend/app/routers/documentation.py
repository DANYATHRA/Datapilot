"""API router for documentation, data dictionaries, process docs, and presentations."""

import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from ..auth import current_user
from ..services import datasets as ds_svc
from ..services import documentation as doc_svc
from ..services import quality as quality_svc

router = APIRouter(prefix="/documentation", tags=["documentation"])


class DeckOptionsIn(BaseModel):
    insights: list[dict] = []
    kpi_values: list[dict] = []


@router.get("/data-dictionary/{dataset_id}")
def get_data_dictionary(dataset_id: str, user=Depends(current_user)):
    try:
        df = ds_svc.load(user["_id"], dataset_id)
        meta = ds_svc.get_meta(user["_id"], dataset_id)
        profile = meta.get("profile", {})
        semantics = profile.get("semantics")
        return doc_svc.generate_data_dictionary(df, profile, meta.get("name", dataset_id), semantics)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/process-doc/{dataset_id}")
def get_process_doc(dataset_id: str, user=Depends(current_user)):
    try:
        meta = ds_svc.get_meta(user["_id"], dataset_id)
        qr = quality_svc.get_scorecard(user["_id"], dataset_id)
        return doc_svc.generate_process_doc(meta, qr)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/stakeholder-summary/{dataset_id}")
def get_stakeholder_summary(dataset_id: str, user=Depends(current_user)):
    try:
        meta = ds_svc.get_meta(user["_id"], dataset_id)
        qr = quality_svc.get_scorecard(user["_id"], dataset_id)
        return doc_svc.generate_stakeholder_summary(meta, qr)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/deck/{dataset_id}")
def download_powerpoint_deck(dataset_id: str, body: DeckOptionsIn = DeckOptionsIn(), user=Depends(current_user)):
    try:
        meta = ds_svc.get_meta(user["_id"], dataset_id)
        profile = meta.get("profile", {})
        qr = quality_svc.get_scorecard(user["_id"], dataset_id)
        pptx_bytes = doc_svc.generate_powerpoint_deck(
            dataset_name=meta.get("name", dataset_id),
            profile=profile,
            insights=body.insights,
            quality_report=qr,
            kpi_values=body.kpi_values,
        )
        return StreamingResponse(
            io.BytesIO(pptx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f'attachment; filename="{meta.get("name", "deck")}_insights.pptx"'},
        )
    except Exception as e:
        raise HTTPException(400, str(e))
