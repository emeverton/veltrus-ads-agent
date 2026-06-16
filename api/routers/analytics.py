"""Endpoints da camada analitica e export BigQuery."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.config import settings
from agent.tools import bigquery_client
from agent.tools.bigquery_analytics import (
    fetch_campaign_daily_rows,
    sync_campaign_daily_to_bigquery,
)
from api.routers.decisions import _require_api_key

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _require_legacy_bigquery() -> None:
    if not bigquery_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="BigQuery nao configurado - defina GOOGLE_CLOUD_PROJECT/GCP_PROJECT_ID e BIGQUERY_DATASET",
        )


class BigQuerySyncRequest(BaseModel):
    campaign_uuid: str | None = None
    since: str | None = None
    limit: int = Field(default=5000, ge=1, le=50000)
    dry_run: bool = False


@router.get("/campaign-daily")
async def list_campaign_daily_analytics(
    campaign_uuid: str | None = Query(default=None),
    since: str | None = Query(default=None, description="Data minima YYYY-MM-DD"),
    limit: int = Query(default=5000, ge=1, le=50000),
    _key: str = Depends(_require_api_key),
) -> list[dict[str, Any]]:
    """Retorna a view analitica diaria ja normalizada para BI."""
    try:
        return fetch_campaign_daily_rows(
            campaign_uuid=campaign_uuid,
            since=since,
            limit=limit,
        )
    except Exception as exc:
        log.error("analytics.campaign_daily.failed", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Analytics query failed: {exc}") from exc


@router.post("/bigquery/sync")
async def sync_bigquery_campaign_daily(
    body: BigQuerySyncRequest,
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Exporta analytics_campaign_daily para BigQuery.

    Use dry_run=true para validar a leitura Supabase e o volume sem tocar na GCP.
    """
    try:
        rows = fetch_campaign_daily_rows(
            campaign_uuid=body.campaign_uuid,
            since=body.since,
            limit=body.limit,
        )
        if body.dry_run:
            return {
                "enabled": settings.bigquery_enabled,
                "dry_run": True,
                "row_count": len(rows),
                "sample": rows[:5],
            }
        return sync_campaign_daily_to_bigquery(rows=rows)
    except RuntimeError as exc:
        log.error("analytics.bigquery.config_failed", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.error("analytics.bigquery.sync_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"BigQuery sync failed: {exc}") from exc


@router.get("/attribution")
async def get_attribution_summary(
    platform: str | None = Query(None, description="meta | google"),
    days: int = Query(30, ge=1, le=365),
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Gap de atribuicao: ROAS plataforma vs ROAS real (CRM) por campanha."""
    _require_legacy_bigquery()
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
    """Performance diaria de uma campanha com ROAS plataforma e real."""
    _require_legacy_bigquery()
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
    """Dispara sync legado Supabase -> BigQuery por tabela operacional."""
    _require_legacy_bigquery()
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
