"""FastAPI — Veltrus Ads Agent API."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent.config import settings
from api.routers import analytics, decisions, leads, run, run_email

app = FastAPI(
    title="Veltrus Ads Agent API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
origins = [o.strip() for o in settings.api_allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(decisions.router)
app.include_router(leads.router)
app.include_router(analytics.router)
app.include_router(run.router)
app.include_router(run_email.router, prefix="/run-email", tags=["email"])

# TODO: add when implemented
# app.include_router(campaigns.router)
# app.include_router(agents.router)
# app.include_router(webhooks.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}
