from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth
from .config import settings
from .routers import (
    cleaning,
    connectors,
    dashboards,
    datasets,
    documentation,
    insights,
    kpis,
    modelling,
    pipeline,
    pipelines,
    projects,
    quality,
    sql,
    survey,
    visuals,
)

from fastapi.encoders import ENCODERS_BY_TYPE
import numpy as np

for t in (np.integer, np.int64, np.int32, np.int16, np.int8, np.uint64, np.uint32, np.uint16, np.uint8):
    ENCODERS_BY_TYPE[t] = int
ENCODERS_BY_TYPE[np.bool_] = bool

app = FastAPI(title="DataPilot API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for r in (
    auth.router,
    datasets.router,
    connectors.router,
    cleaning.router,
    quality.router,
    modelling.router,
    pipelines.router,
    pipeline.router,
    sql.router,
    insights.router,
    survey.router,
    dashboards.router,
    visuals.router,
    kpis.router,
    projects.router,
    documentation.router,
):
    app.include_router(r)


@app.get("/health")
def health():
    from .services import llm
    return {"status": "ok", "llm": llm.available()}
