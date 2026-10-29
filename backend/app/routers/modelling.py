"""API router for data modelling (ERD, relationships, star schema, semantic layer)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import current_user
from ..services import datasets as ds_svc
from ..services import modelling as model_svc

router = APIRouter(prefix="/modelling", tags=["modelling"])


class ModelIn(BaseModel):
    name: str
    description: str = ""
    table_ids: list[str] = []
    relationships: list[dict] = []
    tables_meta: dict | None = None
    semantic_layer: dict | None = None


class DetectRelsIn(BaseModel):
    dataset_ids: list[str]


class ValidateRelIn(BaseModel):
    from_dataset_id: str
    from_column: str
    to_dataset_id: str
    to_column: str
    cardinality: str = "many_to_one"


class DateDimIn(BaseModel):
    start_date: str = "2020-01-01"
    end_date: str = "2030-12-31"
    name: str = "dim_date"


class SemanticLayerIn(BaseModel):
    measures: list[dict] = []
    dimensions: list[dict] = []


@router.get("/models")
def list_models(user=Depends(current_user)):
    return model_svc.list_models(user["_id"])


@router.post("/models")
def create_model(body: ModelIn, user=Depends(current_user)):
    try:
        return model_svc.create_model(user["_id"], body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/models/{model_id}")
def get_model(model_id: str, user=Depends(current_user)):
    try:
        return model_svc.get_model(user["_id"], model_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/models/{model_id}")
def update_model(model_id: str, body: ModelIn, user=Depends(current_user)):
    try:
        return model_svc.update_model(user["_id"], model_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/models/{model_id}")
def delete_model(model_id: str, user=Depends(current_user)):
    try:
        model_svc.delete_model(user["_id"], model_id)
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/detect-keys/{dataset_id}")
def detect_keys(dataset_id: str, user=Depends(current_user)):
    try:
        df = ds_svc.load(user["_id"], dataset_id)
        return model_svc.detect_candidate_keys(df)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/detect-relationships")
def detect_relationships(body: DetectRelsIn, user=Depends(current_user)):
    try:
        tables = {}
        for did in body.dataset_ids:
            try:
                meta = ds_svc.get_meta(user["_id"], did)
                name = meta.get("name", did)
                tables[name] = ds_svc.load(user["_id"], did)
            except Exception:
                continue
        if len(tables) < 2:
            return []
        return model_svc.detect_relationships(tables)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/validate-relationship")
def validate_relationship(body: ValidateRelIn, user=Depends(current_user)):
    try:
        df1 = ds_svc.load(user["_id"], body.from_dataset_id)
        df2 = ds_svc.load(user["_id"], body.to_dataset_id)
        return model_svc.validate_relationship(
            df1, body.from_column, df2, body.to_column, body.cardinality
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/generate-date-dimension")
def generate_date_dimension(body: DateDimIn, user=Depends(current_user)):
    try:
        df = model_svc.generate_date_dimension(body.start_date, body.end_date)
        meta = ds_svc.create_from_dataframe(user["_id"], body.name, df)
        return {"dataset": meta, "rows": len(df)}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/models/{model_id}/semantic-layer")
def get_semantic_layer(model_id: str, user=Depends(current_user)):
    try:
        return model_svc.get_semantic_layer(user["_id"], model_id)
    except Exception as e:
        raise HTTPException(404, str(e))


@router.put("/models/{model_id}/semantic-layer")
def save_semantic_layer(model_id: str, body: SemanticLayerIn, user=Depends(current_user)):
    try:
        return model_svc.save_semantic_layer(user["_id"], model_id, body.measures, body.dimensions)
    except Exception as e:
        raise HTTPException(400, str(e))
