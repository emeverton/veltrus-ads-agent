"""Attribution analytics via BigQuery — camada analítica do Revenue OS."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from agent.config import settings

log = structlog.get_logger(__name__)

_bq_client = None


def _project_id() -> str:
    return settings.google_cloud_project or "veltrus-ads-agent"


def _dataset_id() -> str:
    return settings.bigquery_dataset or "veltrus_attribution"


def _table_ref(table_name: str) -> str:
    return f"{_project_id()}.{_dataset_id()}.{table_name}"


def _get_bq_client():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery

        _bq_client = bigquery.Client(project=_project_id())
    return _bq_client


def get_campaign_real_roas(campaign_uuid: str) -> dict:
    """
    Busca ROAS real do BigQuery (attribution baseado em deals CRM).

    Fallback para Supabase se BigQuery indisponível. Retorna zeros sem exception
    se não houver dados.
    """
    if not campaign_uuid or campaign_uuid in ("None", "n/a", ""):
        return _empty_attribution()
    try:
        client = _get_bq_client()
        query = f"""
            SELECT
              roas_real,
              roas_plataforma,
              revenue_real,
              leads_total,
              deals_closed,
              total_spend
            FROM `{_table_ref("campaign_real_roas")}`
            WHERE campaign_id = @campaign_id
            LIMIT 1
        """
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

        config = QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter("campaign_id", "STRING", campaign_uuid)
            ]
        )
        rows = list(client.query(query, job_config=config).result())
        if not rows:
            return _empty_attribution()
        row = dict(rows[0])
        log.info(
            "attribution.bq.roas",
            campaign_uuid=campaign_uuid,
            roas_real=row.get("roas_real"),
            roas_plataforma=row.get("roas_plataforma"),
            revenue_real=row.get("revenue_real"),
            deals=row.get("deals_closed"),
            source="bigquery",
        )
        return row
    except Exception as exc:
        log.warning("attribution.bq.failed", error=str(exc), fallback="supabase")
        return _attribution_from_supabase(campaign_uuid)


def _attribution_from_supabase(campaign_uuid: str) -> dict:
    """Fallback: lê attribution direto do Supabase."""
    try:
        from agent.tools.supabase_client import get_supabase

        sb = get_supabase()
        result = (
            sb.table("campaign_attribution")
            .select("revenue_closed, leads_total, deals_closed")
            .eq("campaign_id", campaign_uuid)
            .single()
            .execute()
        )
        data = result.data or {}
        log.info(
            "attribution.supabase.roas",
            campaign_uuid=campaign_uuid,
            revenue=data.get("revenue_closed", 0),
            source="supabase",
        )
        return {
            "roas_real": None,
            "roas_plataforma": None,
            "revenue_real": _as_float(data.get("revenue_closed", 0)),
            "leads_total": _as_int(data.get("leads_total", 0)),
            "deals_closed": _as_int(data.get("deals_closed", 0)),
            "total_spend": 0,
        }
    except Exception as exc:
        log.warning("attribution.supabase.failed", error=str(exc))
        return _empty_attribution()


def _empty_attribution() -> dict:
    return {
        "roas_real": None,
        "roas_plataforma": None,
        "revenue_real": 0.0,
        "leads_total": 0,
        "deals_closed": 0,
        "total_spend": 0,
    }


def sync_campaign_spend_to_bq(campaigns: list[dict]) -> None:
    """
    Sincroniza dados de spend das campanhas Meta/Google para o BigQuery.

    Chamado pelo analista após fetch/enrichment de insights. É silencioso em caso
    de falha — nunca quebra o ciclo.
    """
    if not campaigns:
        return
    try:
        client = _get_bq_client()
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        for campaign in campaigns:
            campaign_uuid = campaign.get("_uuid") or campaign.get("campaign_uuid")
            if not campaign_uuid:
                continue
            rows.append(
                {
                    "campaign_id": str(campaign_uuid),
                    "external_campaign_id": str(
                        campaign.get("campaign_id") or campaign.get("id") or ""
                    ),
                    "platform": campaign.get("platform", "meta"),
                    "date": str(campaign.get("date") or today),
                    "spend": _as_float(
                        campaign.get("spend", campaign.get("last_spend_usd", 0))
                    ),
                    "impressions": _as_int(campaign.get("impressions", 0)),
                    "clicks": _as_int(campaign.get("clicks", 0)),
                    "platform_conversions": _as_float(
                        campaign.get("conversions", campaign.get("conversions_click", 0))
                    ),
                    "platform_roas": _as_float(
                        campaign.get("roas", campaign.get("avg_roas_click", 0))
                    ),
                    "synced_at": now,
                }
            )
        if rows:
            errors = client.insert_rows_json(_table_ref("campaign_spend"), rows)
            if errors:
                log.warning("attribution.bq.insert_errors", errors=errors[:3])
            else:
                log.info("attribution.bq.synced", rows=len(rows))
    except Exception as exc:
        log.warning("attribution.bq.sync_failed", error=str(exc))


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
