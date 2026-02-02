from __future__ import annotations

import logging
import os
from typing import List, Dict, Any

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .consultants import KONSULENTER

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(message)s")
logger = logging.getLogger("konsulent_api")

app = FastAPI(title="konsulent_api", version="1.0.0")

# NOTE:
# prometheus-fastapi-instrumentator adds middleware to the app.
# Starlette/FastAPI disallows adding middleware after startup has begun,
# so we must instrument the app at import time (before the server starts).
if os.getenv("METRICS_ENABLED", "true").lower() == "true":
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.on_event("startup")
async def _startup() -> None:
    logger.info('{"service":"konsulent_api","msg":"started"}')


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "konsulent_api"}


@app.get("/konsulenter")
async def get_konsulenter() -> List[Dict[str, Any]]:
    # Hardkodet list (oppgavekrav)
    return [
        {
            "id": k.id,
            "navn": k.navn,
            "ferdigheter": list(k.ferdigheter),
            "belastning_prosent": k.belastning_prosent,
        }
        for k in KONSULENTER
    ]
