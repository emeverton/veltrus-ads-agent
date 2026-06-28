"""Camada analitica BigQuery para Attribution Loop.

Supabase continua sendo o banco operacional. Este modulo le a view analitica
normalizada e publica snapshots idempotentes no BigQuery para BI/modelagem.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from agent.config import settings
from agent.tools.supabase_client import supabase

try:  # pragma: no cover - exercitado apenas quando a lib GCP esta instalada.
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
except ImportError:  # pragma: no cover - permite testes/dev sem credenciais GCP.
    NotFound = None  # type: ignore[assignment]
    bigquery = None  # type: ignore[assignment]


log = structlog.get_logger(__name__)

_BQ_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("analytics_key", "STRING", "REQUIRED"),
    ("synced_at", "TIMESTAMP", "NULLABLE"),
    ("client_uuid", "STRING", "NULLABLE"),
    ("client_name", "STRING", "NULLABLE"),
    ("vertical", "STRING", "NULLABLE"),
    ("ad_account_uuid", "STRING", "NULLABLE"),
    ("account_external_id", "STRING", "NULLABLE"),
    ("platform", "STRING", "NULLABLE"),
    ("campaign_uuid", "STRING", "NULLABLE"),
    ("external_campaign_id", "STRING", "NULLABLE"),
    ("campaign_name", "STRING", "NULLABLE"),
    ("status", "STRING", "NULLABLE"),
    ("objective", "STRING", "NULLABLE"),
    ("date", "DATE", "NULLABLE"),
    ("spend_usd", "FLOAT", "NULLABLE"),
    ("impressions", "INTEGER", "NULLABLE"),
    ("clicks", "INTEGER", "NULLABLE"),
    ("conversions", "FLOAT", "NULLABLE"),
    ("cpa", "FLOAT", "NULLABLE"),
    ("roas_platform", "FLOAT", "NULLABLE"),
    ("ctr", "FLOAT", "NULLABLE"),
    ("attribution_window", "STRING", "NULLABLE"),
    ("confidence_score", "FLOAT", "NULLABLE"),
    ("revenue_closed", "FLOAT", "NULLABLE"),
    ("leads_total", "INTEGER", "NULLABLE"),
    ("deals_closed", "INTEGER", "NULLABLE"),
    ("roas_real", "FLOAT", "NULLABLE"),
    ("metric_created_at", "TIMESTAMP", "NULLABLE"),
)

_BQ_FIELD_NAMES = tuple(field[0] for field in _BQ_FIELDS)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_campaign_daily_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normaliza a linha da view Supabase para o schema do BigQuery."""
    campaign_uuid = _as_str(row.get("campaign_uuid"))
    metric_date = _as_str(row.get("date"))
    analytics_key = _as_str(row.get("analytics_key"))
    if not analytics_key:
        analytics_key = f"{campaign_uuid or 'unknown'}:{metric_date or 'unknown'}"

    return {
        "analytics_key": analytics_key,
        "synced_at": _utc_now_iso(),
        "client_uuid": _as_str(row.get("client_uuid")),
        "client_name": _as_str(row.get("client_name")),
        "vertical": _as_str(row.get("vertical")),
        "ad_account_uuid": _as_str(row.get("ad_account_uuid")),
        "account_external_id": _as_str(row.get("account_external_id")),
        "platform": _as_str(row.get("platform")),
        "campaign_uuid": campaign_uuid,
        "external_campaign_id": _as_str(row.get("external_campaign_id")),
        "campaign_name": _as_str(row.get("campaign_name")),
        "status": _as_str(row.get("status")),
        "objective": _as_str(row.get("objective")),
        "date": metric_date,
        "spend_usd": _as_float(row.get("spend_usd")),
        "impressions": _as_int(row.get("impressions")),
        "clicks": _as_int(row.get("clicks")),
        "conversions": _as_float(row.get("conversions")),
        "cpa": _as_float(row.get("cpa")),
        "roas_platform": _as_float(row.get("roas_platform")),
        "ctr": _as_float(row.get("ctr")),
        "attribution_window": _as_str(row.get("attribution_window")),
        "confidence_score": _as_float(row.get("confidence_score")),
        "revenue_closed": _as_float(row.get("revenue_closed")),
        "leads_total": _as_int(row.get("leads_total")),
        "deals_closed": _as_int(row.get("deals_closed")),
        "roas_real": _as_float(row.get("roas_real")),
        "metric_created_at": _as_str(row.get("metric_created_at")),
    }


def fetch_campaign_daily_rows(
    campaign_uuid: str | None = None,
    since: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Busca linhas da view analytics_campaign_daily no Supabase."""
    safe_limit = max(1, min(limit, 50000))
    query = (
        supabase.table("analytics_campaign_daily")
        .select("*")
        .order("date", desc=False)
        .limit(safe_limit)
    )
    if campaign_uuid:
        query = query.eq("campaign_uuid", campaign_uuid)
    if since:
        query = query.gte("date", since)

    result = query.execute()
    rows = result.data or []
    normalized = [normalize_campaign_daily_row(row) for row in rows]
    log.info("bigquery.analytics.rows_fetched", total=len(normalized))
    return normalized


def _require_bigquery() -> Any:
    if bigquery is None:
        raise RuntimeError(
            "google-cloud-bigquery nao esta instalado. Rode `pip install -r requirements.txt`."
        )
    return bigquery


def _schema() -> list[Any]:
    bq = _require_bigquery()
    return [bq.SchemaField(name, field_type, mode=mode) for name, field_type, mode in _BQ_FIELDS]


def _dataset_id() -> str:
    project_id = settings.gcp_project_id or settings.google_cloud_project
    return f"{project_id}.{settings.bigquery_dataset}"


def _target_table_id() -> str:
    return f"{_dataset_id()}.{settings.bigquery_campaign_daily_table}"


def _table_sql_name(table_id: str) -> str:
    return f"`{table_id}`"


def _build_merge_sql(target_table_id: str, staging_table_id: str) -> str:
    update_assignments = ",\n  ".join(
        f"T.{field} = S.{field}" for field in _BQ_FIELD_NAMES if field != "analytics_key"
    )
    insert_fields = ", ".join(_BQ_FIELD_NAMES)
    insert_values = ", ".join(f"S.{field}" for field in _BQ_FIELD_NAMES)
    return f"""
MERGE {_table_sql_name(target_table_id)} T
USING {_table_sql_name(staging_table_id)} S
ON T.analytics_key = S.analytics_key
WHEN MATCHED THEN UPDATE SET
  {update_assignments}
WHEN NOT MATCHED THEN INSERT ({insert_fields})
VALUES ({insert_values})
""".strip()


def _ensure_dataset_and_table(client: Any) -> None:
    bq = _require_bigquery()
    dataset_id = _dataset_id()
    try:
        client.get_dataset(dataset_id)
    except NotFound:  # type: ignore[misc]
        dataset = bq.Dataset(dataset_id)
        dataset.location = settings.bigquery_location
        client.create_dataset(dataset)
        log.info("bigquery.dataset_created", dataset=dataset_id)

    table_id = _target_table_id()
    try:
        client.get_table(table_id)
    except NotFound:  # type: ignore[misc]
        table = bq.Table(table_id, schema=_schema())
        client.create_table(table)
        log.info("bigquery.table_created", table=table_id)


def sync_campaign_daily_to_bigquery(
    rows: list[dict[str, Any]] | None = None,
    campaign_uuid: str | None = None,
    since: str | None = None,
    limit: int = 5000,
    client: Any | None = None,
) -> dict[str, Any]:
    """Exporta a view diaria para BigQuery via MERGE idempotente."""
    normalized_rows = rows
    if normalized_rows is None:
        normalized_rows = fetch_campaign_daily_rows(
            campaign_uuid=campaign_uuid,
            since=since,
            limit=limit,
        )
    else:
        normalized_rows = [normalize_campaign_daily_row(row) for row in normalized_rows]

    if not settings.bigquery_enabled:
        return {
            "enabled": False,
            "skipped": True,
            "row_count": len(normalized_rows),
            "table": _target_table_id(),
        }

    if not normalized_rows:
        return {
            "enabled": True,
            "skipped": True,
            "row_count": 0,
            "table": _target_table_id(),
        }

    bq = _require_bigquery()
    project_id = settings.gcp_project_id or settings.google_cloud_project
    bq_client = client or bq.Client(project=project_id)
    _ensure_dataset_and_table(bq_client)

    target_table_id = _target_table_id()
    staging_table_id = (
        f"{_dataset_id()}._staging_{settings.bigquery_campaign_daily_table}_"
        f"{uuid.uuid4().hex}"
    )
    staging_table = bq.Table(staging_table_id, schema=_schema())
    bq_client.create_table(staging_table)

    errors: list[Any] = []
    try:
        job_config = bq.LoadJobConfig(
            schema=_schema(),
            write_disposition=bq.WriteDisposition.WRITE_TRUNCATE,
            ignore_unknown_values=True,
        )
        load_job = bq_client.load_table_from_json(
            normalized_rows,
            staging_table_id,
            job_config=job_config,
        )
        load_job.result()
        if getattr(load_job, "errors", None):
            errors.extend(load_job.errors)

        merge_job = bq_client.query(_build_merge_sql(target_table_id, staging_table_id))
        merge_job.result()
        if getattr(merge_job, "errors", None):
            errors.extend(merge_job.errors)
    finally:
        bq_client.delete_table(staging_table_id, not_found_ok=True)

    log.info(
        "bigquery.analytics.synced",
        table=target_table_id,
        rows=len(normalized_rows),
        errors=len(errors),
    )
    return {
        "enabled": True,
        "skipped": False,
        "row_count": len(normalized_rows),
        "table": target_table_id,
        "errors": errors,
    }
