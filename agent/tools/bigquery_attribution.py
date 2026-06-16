"""Attribution analytics via BigQuery — camada analítica do Revenue OS."""
from __future__ import annotations

import structlog

from agent.config import settings

log = structlog.get_logger(__name__)

_bq_client = None

DEFAULT_PROJECT = "veltrus-ads-agent"
DEFAULT_DATASET = "veltrus_attribution"


def _project_id() -> str:
    return (
        settings.gcp_project_id
        or settings.google_cloud_project
        or DEFAULT_PROJECT
    )


def _dataset_id() -> str:
    return settings.bigquery_dataset or DEFAULT_DATASET


def _get_bq_client():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery

        _bq_client = bigquery.Client(project=_project_id())
    return _bq_client


def get_campaign_real_roas(campaign_uuid: str) -> dict:
    """
    Busca ROAS real do BigQuery (attribution baseado em deals CRM).
    Fallback para Supabase se BigQuery indisponível.
    Retorna zeros sem exception se não houver dados.
    """
    if not campaign_uuid or campaign_uuid in ("None", "n/a", ""):
        return _empty_attribution()
    try:
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

        client = _get_bq_client()
        project = _project_id()
        dataset = _dataset_id()
        query = f"""
            SELECT
              roas_real,
              roas_plataforma,
              revenue_real,
              leads_total,
              deals_closed,
              total_spend
            FROM `{project}.{dataset}.campaign_real_roas`
            WHERE campaign_id = @campaign_id
            LIMIT 1
        """
        config = QueryJobConfig(
            query_parameters=[ScalarQueryParameter("campaign_id", "STRING", campaign_uuid)]
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
        r = (
            sb.table("campaign_attribution")
            .select("revenue_closed, leads_total, deals_closed")
            .eq("campaign_id", campaign_uuid)
            .single()
            .execute()
        )
        data = r.data or {}
        log.info(
            "attribution.supabase.roas",
            campaign_uuid=campaign_uuid,
            revenue=data.get("revenue_closed", 0),
            source="supabase",
        )
        return {
            "roas_real": None,
            "roas_plataforma": None,
            "revenue_real": float(data.get("revenue_closed", 0)),
            "leads_total": data.get("leads_total", 0),
            "deals_closed": data.get("deals_closed", 0),
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
    Chamado pelo analista após fetch de insights.
    Silencioso em caso de falha — nunca quebra o ciclo.
    """
    if not campaigns:
        return
    try:
        from datetime import datetime, timezone

        client = _get_bq_client()
        project = _project_id()
        dataset = _dataset_id()
        table_ref = f"{project}.{dataset}.campaign_spend"
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for c in campaigns:
            campaign_uuid = c.get("_uuid") or c.get("campaign_uuid")
            if not campaign_uuid:
                continue
            rows.append({
                "campaign_id": campaign_uuid,
                "external_campaign_id": str(c.get("campaign_id", "")),
                "platform": c.get("platform", "meta"),
                "date": str(c.get("date", datetime.now(timezone.utc).date())),
                "spend": float(c.get("spend", c.get("last_spend_usd", 0)) or 0),
                "impressions": int(c.get("impressions", 0)),
                "clicks": int(c.get("clicks", 0)),
                "platform_conversions": float(
                    c.get("conversions", c.get("conversions_click", 0)) or 0
                ),
                "platform_roas": float(c.get("roas", c.get("avg_roas_click", 0)) or 0),
                "synced_at": now,
            })
        if rows:
            errors = client.insert_rows_json(table_ref, rows)
            if errors:
                log.warning("attribution.bq.insert_errors", errors=errors[:3])
            else:
                log.info("attribution.bq.synced", rows=len(rows))
    except Exception as exc:
        log.warning("attribution.bq.sync_failed", error=str(exc))
