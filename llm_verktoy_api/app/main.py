from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.settings import settings
from app.service import LLMService
from app.openrouter_key_monitor import openrouter_key_monitor_loop
from app.metrics import audit_events_total, rate_limit_hits_total, dependency_up, service_health_ok

LOG_LEVEL = settings.log_level.upper()
logging.basicConfig(level=LOG_LEVEL, format="%(message)s")
logger = logging.getLogger("llm_verktoy_api")

app = FastAPI(title="llm_verktoy_api", version="1.0.0")

# NOTE:
# prometheus-fastapi-instrumentator adds middleware to the app.
# Starlette/FastAPI disallows adding middleware after startup has begun,
# so we instrument at import time (before the server starts).
if settings.metrics_enabled:
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.rate_limit_storage_uri,
)
service = LLMService()


@app.on_event("startup")
async def _startup() -> None:
    logger.info('{"service":"llm_verktoy_api","msg":"started","openrouter_enabled":%s,"local_gguf_enabled":%s}' % (
        str(settings.openrouter_enabled).lower(),
        str(settings.local_gguf_enabled).lower(),
    ))

    # Start the OpenRouter key usage/limit poller *inside* the FastAPI startup
    # event so we are guaranteed to have a running asyncio loop.
    # (Calling asyncio.create_task at import time can silently fail and result
    # in Grafana panels showing "No data" for key usage/limits.)
    if settings.metrics_enabled:
        asyncio.create_task(openrouter_key_monitor_loop())





@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    t0 = time.time()
    try:
        response = await call_next(request)
        duration_ms = (time.time() - t0) * 1000
        logger.info(
            '{"ts":"%s","level":"INFO","logger":"llm_verktoy_api","msg":"request","request_id":"%s","method":"%s","path":"%s","duration_ms":%.2f}'
            % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), request_id, request.method, request.url.path, duration_ms)
        )
        response.headers["x-request-id"] = request_id
        return response
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        logger.error(
            '{"ts":"%s","level":"ERROR","logger":"llm_verktoy_api","msg":"error","request_id":"%s","error":"%s","duration_ms":%.2f}'
            % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), request_id, str(e).replace('"','\"'), duration_ms)
        )
        return JSONResponse(status_code=500, content={"error": "internal_error", "request_id": request_id})


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    request_id = getattr(request.state, "request_id", "n/a")
    rate_limit_hits_total.labels(request.url.path).inc()
    return JSONResponse(status_code=429, content={"error": "rate_limited", "request_id": request_id})


@app.get("/health")
async def health() -> Dict[str, Any]:
    deps: Dict[str, Any] = {
        "konsulent_api": {"ok": True},
        "openrouter": {"enabled": settings.openrouter_enabled},
        "local_gguf": {"enabled": settings.local_gguf_enabled},
        "redis": {"enabled": settings.redis_enabled},
    }

    # Konsulent API ping
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.konsulent_api_url}/health")
            deps["konsulent_api"]["ok"] = r.status_code == 200
    except Exception as e:
        deps["konsulent_api"] = {"ok": False, "error": str(e)}

    status = "ok" if deps["konsulent_api"]["ok"] else "degraded"
    dependency_up.labels("konsulent_api").set(1.0 if deps["konsulent_api"].get("ok") else 0.0)
    service_health_ok.set(1.0 if status == "ok" else 0.0)
    logger.info('{"type":"health","status":"%s","deps":%s}' % (status, json.dumps(deps, ensure_ascii=False)))
    return {"status": status, "service": "llm_verktoy_api", "deps": deps}


@app.get("/audit")
async def audit() -> Dict[str, Any]:
    # Return full audit log (for demo)
    return {"events": service.audit.list()}


@app.get("/openrouter/usage")
async def openrouter_usage() -> Dict[str, Any]:
    return {
        "daily_cost_credits": service.usage.daily_cost(),
        "events": service.usage.list(),
    }


@app.get("/openrouter/key")
async def openrouter_key() -> Dict[str, Any]:
    if not settings.openrouter_api_key:
        return {"ok": False, "error": "OPENROUTER_API_KEY not set"}

    # Docs: GET https://openrouter.ai/api/v1/key
    url = "https://openrouter.ai/api/v1/key"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
        return {"ok": r.status_code == 200, "status_code": r.status_code, "data": r.json()}


@app.get("/tilgjengelige-konsulenter/sammendrag")
@limiter.limit(lambda: settings.rate_limit_default if settings.rate_limit_enabled else "1000000/minute")
async def tilgjengelige_konsulenter_sammendrag(
    request: Request,
    min_tilgjengelighet_prosent: int = Query(..., ge=0, le=100),
    påkrevd_ferdighet: str = Query(..., min_length=1, max_length=64),
    openrouter_model: Optional[str] = Query(None, min_length=1, max_length=128),
    prompt_style: Optional[str] = Query("strict", min_length=1, max_length=32),
) -> Dict[str, Any]:
    request_id = request.state.request_id

    konsulenter, cached = await service.fetch_konsulenter()

    sammendrag, fallback_used, fallback_reason, meta = await service.generate_sammendrag(
        request_id=request_id,
        min_tilgjengelighet=min_tilgjengelighet_prosent,
        pakrevd_ferdighet=påkrevd_ferdighet,
        konsulenter=konsulenter,
        konsulenter_cached=cached,
        model_override=openrouter_model,
        prompt_style=prompt_style or "strict",
    )

    meta["fallback_used"] = bool(fallback_used)
    meta["fallback_reason"] = fallback_reason
    meta["request_id"] = request_id

    # Audit the output (scrubbed)
    service.audit.add(request_id, "sammendrag", {"min": min_tilgjengelighet_prosent, "skill": påkrevd_ferdighet, "fallback": fallback_used}, ok=True)
    audit_events_total.labels("sammendrag","true").inc()

    return {"sammendrag": sammendrag, "meta": meta}
