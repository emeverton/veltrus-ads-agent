"""Cliente BigQuery para a camada de analytics do Veltrus Ads Agent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from agent.config import settings

log = structlog.get_logger(__name__)

_client: Any | None = None


def is_configured() -> bool:
    """Retorna True se o projeto GCP e dataset BigQuery estão configurados."""
    return bool((settings.gcp_project_id or settings.google_cloud_project) and settings.bigquery_dataset)


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    if not is_configured():
        raise RuntimeError("BigQuery nao configurado - defina GOOGLE_CLOUD_PROJECT/GCP_PROJECT_ID e BIGQUERY_DATASET")
    from google.cloud import bigquery
    from google.oauth2 import service_account

    if settings.bigquery_credentials_json:
        info = json.loads(settings.bigquery_credentials_json)
        credentials = service_account.Credentials.from_service_account_info(info)
        _client = bigquery.Client(
            project=settings.gcp_project_id or settings.google_cloud_project,
            credentials=credentials,
        )
    else:
        _client = bigquery.Client(project=settings.gcp_project_id or settings.google_cloud_project)
    return _client


def table_ref(table_name: str) -> str:
    project_id = settings.gcp_project_id or settings.google_cloud_project
    return f"`{project_id}.{settings.bigquery_dataset}.{table_name}`"


def ensure_dataset() -> None:
    """Cria o dataset BigQuery se não existir."""
    from google.cloud import bigquery

    client = _get_client()
    dataset_id = f"{settings.gcp_project_id or settings.google_cloud_project}.{settings.bigquery_dataset}"
    try:
        client.get_dataset(dataset_id)
        log.info("bigquery.dataset.exists", dataset=dataset_id)
    except Exception:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = settings.bigquery_location
        client.create_dataset(dataset, exists_ok=True)
        log.info("bigquery.dataset.created", dataset=dataset_id)


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Executa query parametrizada e retorna lista de dicts."""
    from google.cloud import bigquery

    client = _get_client()
    job_config = bigquery.QueryJobConfig()
    if params:
        query_params = []
        for key, value in params.items():
            if value is None:
                continue
            if key == "days":
                query_params.append(bigquery.ScalarQueryParameter(key, "INT64", int(value)))
            else:
                query_params.append(bigquery.ScalarQueryParameter(key, "STRING", str(value)))
        job_config.query_parameters = query_params
    result = client.query(sql, job_config=job_config).result()
    return [dict(row.items()) for row in result]


def insert_rows(table_name: str, rows: list[dict[str, Any]]) -> int:
    """Insere linhas na tabela BigQuery. Retorna quantidade inserida."""
    if not rows:
        return 0
    client = _get_client()
    project_id = settings.gcp_project_id or settings.google_cloud_project
    table_id = f"{project_id}.{settings.bigquery_dataset}.{table_name}"
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row.setdefault("synced_at", now)
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        log.error("bigquery.insert.errors", table=table_name, errors=errors[:3])
        raise RuntimeError(f"BigQuery insert failed: {errors[0]}")
    log.info("bigquery.insert.ok", table=table_name, count=len(rows))
    return len(rows)


def get_attribution_summary(
    platform: str | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Retorna gap de atribuição (ROAS plataforma vs ROAS real) por campanha."""
    sql = f"""
        SELECT
          campaign_id,
          campaign_name,
          platform,
          revenue_closed,
          leads_total,
          deals_closed,
          spend_total,
          roas_platform_avg,
          roas_real,
          roas_gap
        FROM {table_ref("attribution_gap")}
        WHERE 1=1
    """
    if platform:
        sql += " AND platform = @platform"
    sql += " ORDER BY revenue_closed DESC LIMIT 100"
    return query(sql, {"platform": platform} if platform else None)


def get_campaign_performance(
    campaign_id: str,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Retorna performance diária com ROAS plataforma e real."""
    sql = f"""
        SELECT
          campaign_id,
          campaign_name,
          platform,
          date,
          spend,
          impressions,
          clicks,
          conversions,
          cpa,
          roas_platform,
          ctr,
          attribution_window,
          confidence_score,
          revenue_closed,
          leads_total,
          deals_closed,
          roas_real
        FROM {table_ref("campaign_performance")}
        WHERE campaign_id = @campaign_id
          AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        ORDER BY date DESC
    """
    return query(sql, {"campaign_id": campaign_id, "days": days})
