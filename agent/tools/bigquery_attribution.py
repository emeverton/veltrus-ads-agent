"""Attribution analytics via BigQuery — camada analítica do Revenue OS.

BigQuery é usado EXCLUSIVAMENTE como banco analítico (não operacional).
Todas as operações são tolerantes a falha: nunca quebram o ciclo do agente.
Fallback: Supabase campaign_attribution view.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

_bq_client = None


def _get_bq_client():
    """Singleton do BigQuery Client — inicializado sob demanda."""
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        import os
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "veltrus-ads-agent")
        _bq_client = bigquery.Client(project=project)
    return _bq_client


def get_campaign_real_roas(campaign_uuid: str) -> dict:
    """Busca ROAS real do BigQuery (attribution baseado em deals CRM).

    Retorna zeros sem exception se não houver dados ou se BigQuery estiver indisponível.
    Fallback automático para Supabase quando BigQuery falha.
    """
    if not campaign_uuid or str(campaign_uuid).strip() in ("None", "n/a", "n/d", ""):
        return _empty_attribution()
    try:
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
        import os
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "veltrus-ads-agent")
        dataset = os.environ.get("BIGQUERY_DATASET", "veltrus_attribution")

        client = _get_bq_client()
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
            query_parameters=[
                ScalarQueryParameter("campaign_id", "STRING", str(campaign_uuid))
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
        return {
            "roas_real":       row.get("roas_real"),
            "roas_plataforma": row.get("roas_plataforma"),
            "revenue_real":    float(row.get("revenue_real") or 0),
            "leads_total":     int(row.get("leads_total") or 0),
            "deals_closed":    int(row.get("deals_closed") or 0),
            "total_spend":     float(row.get("total_spend") or 0),
        }
    except Exception as exc:
        log.warning("attribution.bq.failed", error=str(exc), fallback="supabase")
        return _attribution_from_supabase(campaign_uuid)


def _attribution_from_supabase(campaign_uuid: str) -> dict:
    """Fallback: lê attribution direto da view campaign_attribution no Supabase."""
    try:
        from agent.tools.supabase_client import get_supabase
        sb = get_supabase()
        r = (
            sb.table("campaign_attribution")
            .select("revenue_closed, leads_total, deals_closed")
            .eq("campaign_id", campaign_uuid)
            .maybe_single()
            .execute()
        )
        data = (r.data if r else None) or {}
        log.info(
            "attribution.supabase.roas",
            campaign_uuid=campaign_uuid,
            revenue=data.get("revenue_closed", 0),
            source="supabase",
        )
        return {
            "roas_real":       None,
            "roas_plataforma": None,
            "revenue_real":    float(data.get("revenue_closed") or 0),
            "leads_total":     int(data.get("leads_total") or 0),
            "deals_closed":    int(data.get("deals_closed") or 0),
            "total_spend":     0.0,
        }
    except Exception as exc:
        log.warning("attribution.supabase.failed", error=str(exc))
        return _empty_attribution()


def _empty_attribution() -> dict:
    return {
        "roas_real":       None,
        "roas_plataforma": None,
        "revenue_real":    0.0,
        "leads_total":     0,
        "deals_closed":    0,
        "total_spend":     0.0,
    }


def sync_campaign_spend_to_bq(campaigns: list) -> None:
    """Sincroniza dados de spend das campanhas Meta/Google para o BigQuery.

    Chamado pelo analista após fetch de insights.
    Silencioso em caso de falha — nunca bloqueia o ciclo do agente.
    BigQuery é destino analítico, não operacional.
    """
    if not campaigns:
        return
    try:
        from datetime import datetime, timezone
        import os
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "veltrus-ads-agent")
        dataset = os.environ.get("BIGQUERY_DATASET", "veltrus_attribution")

        client = _get_bq_client()
        table_ref = f"{project}.{dataset}.campaign_spend"
        rows = []
        now = datetime.now(timezone.utc).isoformat()

        for c in campaigns:
            campaign_uuid = c.get("_uuid") or c.get("campaign_uuid")
            if not campaign_uuid:
                continue
            rows.append({
                "campaign_id":          str(campaign_uuid),
                "external_campaign_id": str(c.get("campaign_id") or ""),
                "platform":             c.get("platform", "meta"),
                "date":                 str(c.get("date", datetime.now().date())),
                "spend":                float(c.get("spend") or c.get("last_spend_usd") or 0),
                "impressions":          int(c.get("impressions") or 0),
                "clicks":               int(c.get("clicks") or 0),
                "platform_conversions": float(c.get("conversions") or c.get("conversions_click") or 0),
                "platform_roas":        float(c.get("roas") or c.get("avg_roas_click") or c.get("roas_click") or 0),
                "synced_at":            now,
            })

        if not rows:
            return

        errors = client.insert_rows_json(table_ref, rows)
        if errors:
            log.warning("attribution.bq.insert_errors", errors=errors[:3], rows_attempted=len(rows))
        else:
            log.info("attribution.bq.synced", rows=len(rows))
    except Exception as exc:
        log.warning("attribution.bq.sync_failed", error=str(exc))
