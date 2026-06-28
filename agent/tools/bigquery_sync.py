"""Sync Supabase → BigQuery — lógica compartilhada entre script CLI e API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from agent.tools import bigquery_client
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)

SYNC_TABLES = ("campaigns", "daily_metrics", "leads", "deals", "agent_decisions")

TABLE_SELECT: dict[str, str] = {
    "campaigns": "id, account_id, campaign_id, name, platform, status, objective, daily_budget, created_at, updated_at",
    "daily_metrics": (
        "id, campaign_id, date, spend, impressions, clicks, conversions, "
        "cpa, roas, ctr, attribution_window, confidence_score"
    ),
    "leads": (
        "id, client_id, campaign_id, external_campaign_id, phone, name, "
        "crm_deal_id, crm_status, lead_source, created_at, updated_at"
    ),
    "deals": "id, lead_id, campaign_id, client_id, crm_deal_id, revenue_amount, currency, closed_at, created_at",
    "agent_decisions": "id, campaign_id, action_type, reasoning, payload, executed, approved_by, approved_at, created_at",
}


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            out[key] = None
        elif isinstance(value, (dict, list)):
            out[key] = value
        else:
            out[key] = str(value) if key.endswith("_id") or key == "id" else value
    out["synced_at"] = datetime.now(timezone.utc).isoformat()
    return out


def fetch_supabase_table(table: str) -> list[dict[str, Any]]:
    select_cols = TABLE_SELECT.get(table, "*")
    result = supabase.table(table).select(select_cols).execute()
    rows = result.data or []
    log.info("sync.fetch", table=table, count=len(rows))
    return [_normalize_row(r) for r in rows]


def sync_table(table: str) -> int:
    rows = fetch_supabase_table(table)
    if not rows:
        return 0
    return bigquery_client.insert_rows(table, rows)


def run_sync(tables: list[str] | None = None) -> dict[str, int]:
    if not bigquery_client.is_configured():
        raise RuntimeError(
            "BigQuery não configurado. Defina GCP_PROJECT_ID e BIGQUERY_DATASET no .env"
        )
    bigquery_client.ensure_dataset()
    targets = tables or list(SYNC_TABLES)
    results: dict[str, int] = {}
    for table in targets:
        if table not in SYNC_TABLES:
            log.warning("sync.skip_unknown", table=table)
            continue
        try:
            results[table] = sync_table(table)
        except Exception as exc:
            log.error("sync.table_failed", table=table, error=str(exc))
            results[table] = -1
    log.info("sync.complete", results=results)
    return results
