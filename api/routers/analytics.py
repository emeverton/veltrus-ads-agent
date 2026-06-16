"""api/routers/analytics.py — Endpoints de analytics via BigQuery."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from agent.tools import bigquery_client
from api.routers.decisions import _require_api_key

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _require_bigquery() -> None:
    if not bigquery_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="BigQuery não configurado — defina GCP_PROJECT_ID e BIGQUERY_DATASET",
        )


@router.get("/attribution")
async def get_attribution_summary(
    platform: str | None = Query(None, description="meta | google"),
    days: int = Query(30, ge=1, le=365),
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Gap de atribuição: ROAS plataforma vs ROAS real (CRM) por campanha."""
    _require_bigquery()
    try:
        rows = bigquery_client.get_attribution_summary(platform=platform, days=days)
    except Exception as exc:
        log.error("analytics.attribution.failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"BigQuery query failed: {exc}") from exc
    return {"platform": platform, "days": days, "campaigns": rows, "total": len(rows)}


@router.get("/campaigns/{campaign_id}/performance")
async def get_campaign_performance(
    campaign_id: str,
    days: int = Query(30, ge=1, le=365),
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Performance diária de uma campanha com ROAS plataforma e real."""
    _require_bigquery()
    try:
        rows = bigquery_client.get_campaign_performance(campaign_id=campaign_id, days=days)
    except Exception as exc:
        log.error("analytics.performance.failed", campaign_id=campaign_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"BigQuery query failed: {exc}") from exc
    return {"campaign_id": campaign_id, "days": days, "metrics": rows}


@router.post("/sync")
async def trigger_sync(
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Dispara sync manual Supabase → BigQuery."""
    _require_bigquery()
    from agent.tools.bigquery_sync import run_sync

    try:
        results = run_sync()
    except Exception as exc:
        log.error("analytics.sync.failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    failed = [t for t, n in results.items() if n < 0]
    if failed:
        raise HTTPException(status_code=500, detail={"failed_tables": failed, "results": results})
    return {"status": "ok", "results": results}
