"""API router for multi-source data connectors."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import current_user
from ..services import connectors as conn_svc
from ..services import datasets as ds_svc
from ..services.profiling import profile

router = APIRouter(prefix="/connectors", tags=["connectors"])


class ConnectionIn(BaseModel):
    type: str
    name: str
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    schema_name: str = ""
    file_path: str = ""
    dsn: str = ""
    connection_string: str = ""
    base_url: str = ""
    json_path: str = "data"
    pagination_type: str = "none"
    page_param: str = "page"
    page_size_param: str = "per_page"
    page_size: int = 100
    max_pages: int = 10
    headers: dict | None = None
    url: str = ""


class PullIn(BaseModel):
    table: str | None = None
    sql: str | None = None
    sample_mode: str = "full"
    sample_n: int = 1000
    columns: list[str] | None = None
    schema_name: str | None = None
    save_as: str | None = None


@router.get("")
def list_connections(user=Depends(current_user)):
    return conn_svc.list_connections(user["_id"])


@router.post("")
def create_connection(body: ConnectionIn, user=Depends(current_user)):
    try:
        return conn_svc.create_connection(user["_id"], body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{conn_id}")
def get_connection(conn_id: str, user=Depends(current_user)):
    try:
        doc = conn_svc.get_connection(user["_id"], conn_id)
        return conn_svc._sanitize_conn(doc)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/{conn_id}")
def update_connection(conn_id: str, body: ConnectionIn, user=Depends(current_user)):
    try:
        return conn_svc.update_connection(user["_id"], conn_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{conn_id}")
def delete_connection(conn_id: str, user=Depends(current_user)):
    try:
        conn_svc.delete_connection(user["_id"], conn_id)
        return {"deleted": conn_id}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{conn_id}/test")
def test_connection(conn_id: str, user=Depends(current_user)):
    return conn_svc.test_connection(user["_id"], conn_id)


@router.get("/{conn_id}/schema")
def browse_schema(conn_id: str, user=Depends(current_user)):
    try:
        return conn_svc.browse_schema(user["_id"], conn_id)
    except Exception as e:
        raise HTTPException(400, f"Schema browse failed: {e}")


@router.post("/{conn_id}/pull")
def pull_data(conn_id: str, body: PullIn, user=Depends(current_user)):
    """Pull data from a connection and optionally save as a dataset."""
    try:
        df, meta = conn_svc.pull_data(
            user["_id"], conn_id,
            table=body.table, sql=body.sql,
            sample_mode=body.sample_mode, sample_n=body.sample_n,
            columns=body.columns, schema=body.schema_name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Pull failed: {e}")

    result = {"pull": meta, "rows": len(df), "cols": df.shape[1], "columns": list(df.columns)}

    # Save as a named dataset if requested
    if body.save_as and not df.empty:
        doc = ds_svc.create_dataset(user["_id"], body.save_as, df)
        result["dataset_id"] = doc["_id"]
        result["dataset_name"] = doc["name"]

    return result


@router.get("/{conn_id}/history")
def pull_history(conn_id: str, user=Depends(current_user)):
    return conn_svc.get_pull_history(user["_id"], conn_id)
