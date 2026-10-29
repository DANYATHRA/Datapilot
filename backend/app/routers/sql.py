import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import current_user
from ..db import queries
from ..services import llm, nl2sql, sql_engine
from ..services.sql_engine import SQLError

router = APIRouter(tags=["sql"])


class SQLIn(BaseModel):
    sql: str
    max_rows: int | None = None


@router.post("/sql/run")
def run(body: SQLIn, user=Depends(current_user)):
    try:
        return sql_engine.run(user["_id"], body.sql, body.max_rows)
    except SQLError as e:
        raise HTTPException(400, str(e))


@router.post("/sql/explain")
def explain(body: SQLIn, user=Depends(current_user)):
    try:
        return {"plan": sql_engine.explain(user["_id"], body.sql)}
    except SQLError as e:
        raise HTTPException(400, str(e))


@router.get("/sql/schema")
def schema(user=Depends(current_user)):
    from ..db import datasets
    from ..services.datasets import load_df
    return [{"table": d["table"], "dataset_id": d["_id"],
             "columns": [{"name": c, "dtype": str(t)} for c, t in load_df(d).dtypes.items()]}
            for d in datasets.find({"owner": user["_id"]})]


class AskIn(BaseModel):
    question: str | None = None
    query: str | None = None
    dataset_id: str | None = None


@router.post("/insights/nl2sql")
@router.post("/sql/ask-data")
def ask(body: AskIn, user=Depends(current_user)):
    q = body.question or body.query or ""
    try:
        res = nl2sql.ask(user["_id"], q)
        if "answer" not in res:
            res["answer"] = res.get("explanation") or f"Executed SQL: {res.get('sql', '')}"
        return res
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))


class SaveQ(BaseModel):
    name: str
    sql: str


@router.get("/queries")
def list_queries(user=Depends(current_user)):
    return [{"id": q["_id"], "name": q["name"], "sql": q["sql"]} for q in queries.find({"owner": user["_id"]})]


@router.post("/queries")
def save_query(body: SaveQ, user=Depends(current_user)):
    qid = uuid.uuid4().hex[:10]
    queries.insert_one({"_id": qid, "owner": user["_id"], "name": body.name, "sql": body.sql})
    return {"id": qid}


@router.delete("/queries/{qid}")
def delete_query(qid: str, user=Depends(current_user)):
    queries.delete_one({"_id": qid, "owner": user["_id"]})
    return {"deleted": qid}
