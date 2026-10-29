import json
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import current_user
from ..services import auto_insights, llm
from ..services import datasets as ds

router = APIRouter(prefix="/insights", tags=["insights"])

NARRATE_SYS = """You write short executive summaries for business analysts.
You are given a JSON list of statistically-detected insights, each with an id like I3.
Write 3-6 bullet lines. Every line MUST end with the id(s) of the insight(s) it relies on in square brackets, e.g. [I2].
Use only facts present in the JSON. Do not invent numbers, causes or recommendations unsupported by the data."""


def verified_narrative(insights: list[dict]) -> tuple[str, str]:
    ids = {i["id"] for i in insights}
    fallback = "\n".join(f"• {i['title']}. {i['detail']} [{i['id']}]" for i in insights[:6]) or "No notable patterns detected."
    if not insights or not llm.available():
        return fallback, "template"
    payload = json.dumps([{k: i[k] for k in ("id", "type", "title", "detail")} for i in insights])
    try:
        text = llm.complete(NARRATE_SYS, [{"role": "user", "content": payload}], 800)
    except Exception:
        return fallback, "template"
    kept = []  # hallucination guard: drop any line without a valid citation
    for line in text.splitlines():
        cites = re.findall(r"\[(I\d+)\]", line)
        if line.strip() and cites and all(c in ids for c in cites):
            kept.append(line.strip())
    return ("\n".join(kept), "llm (citations verified)") if kept else (fallback, "template")


from ..gating import require_dataset


class GenIn(BaseModel):
    dataset_id: str
    narrate: bool = True


@router.post("/generate")
def generate(body: GenIn, user=Depends(current_user)):
    require_dataset(user)
    d = ds.get_dataset(user["_id"], body.dataset_id)
    insights = auto_insights.generate(ds.load_df(d), d["table"])
    narrative, by = verified_narrative(insights) if body.narrate else ("", "none")
    return {"insights": insights, "narrative": narrative, "narrated_by": by}
