from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import current_user
from ..gating import require_dataset
from ..services import datasets as ds, survey_stats as ss
from ..services.util import to_json_table

router = APIRouter(prefix="/survey", tags=["survey"])


def _df(user, ds_id, cols):
    require_dataset(user)
    d = ds.get_dataset(user["_id"], ds_id)
    df = ds.load_df(d)
    missing = [c for c in cols if c and c not in df.columns]
    if missing:
        raise HTTPException(400, f"Unknown column(s): {missing}")
    return df


class CrossIn(BaseModel):
    dataset_id: str
    row: str
    col: str
    weight: str | None = None


@router.post("/crosstab")
def crosstab(b: CrossIn, user=Depends(current_user)):
    df = _df(user, b.dataset_id, [b.row, b.col, b.weight])
    try:
        r = ss.crosstab(df, b.row, b.col, b.weight)
    except ValueError as e:
        raise HTTPException(400, str(e))
    out = {"counts": to_json_table(r["counts"].reset_index().astype(object)),
           "row_pct": to_json_table(r["row_pct"].reset_index().astype(object))}
    out["test"] = r.get("test")
    return out


class CompareIn(BaseModel):
    dataset_id: str
    value: str
    group: str


@router.post("/compare")
def compare(b: CompareIn, user=Depends(current_user)):
    df = _df(user, b.dataset_id, [b.value, b.group])
    try:
        return ss.compare_groups(df, b.value, b.group)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


class LikertIn(BaseModel):
    dataset_id: str
    columns: list[str]
    scale_max: int = 5


@router.post("/likert")
def likert(b: LikertIn, user=Depends(current_user)):
    df = _df(user, b.dataset_id, b.columns)
    return ss.likert(df, b.columns, b.scale_max)
