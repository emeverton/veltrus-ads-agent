"""Registro automático de campanhas da API no Supabase."""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any

import structlog

from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)

_campaign_id_map: ContextVar[dict[str, str]] = ContextVar("campaign_id_map", default={})


def get_campaign_id_map() -> dict[str, str]:
    """Retorna o mapa {campaign_id_externo: uuid_interno} do ciclo atual."""
    return _campaign_id_map.get()


def set_campaign_id_map(id_map: dict[str, str]) -> None:
    """Define o mapa de campanhas para o ciclo atual."""
    _campaign_id_map.set(dict(id_map))


def merge_campaign_id_map(extra: dict[str, str]) -> dict[str, str]:
    """Mescla entradas no mapa do ciclo e retorna o mapa atualizado."""
    merged = {**get_campaign_id_map(), **extra}
    _campaign_id_map.set(merged)
    return merged


def _normalize_status(raw_status: Any, platform: str) -> str:
    """Converte status da API para o enum do Supabase (active|paused|archived)."""
    status = str(raw_status or "").upper()
    if platform == "google":
        if status == "ENABLED":
            return "active"
        if status == "PAUSED":
            return "paused"
        if status == "REMOVED":
            return "archived"
        return "active"
    if status == "ACTIVE":
        return "active"
    if status == "PAUSED":
        return "paused"
    if status == "ARCHIVED":
        return "archived"
    return "active"


def _daily_budget(campaign: dict[str, Any]) -> float | None:
    if campaign.get("daily_budget_usd") is not None:
        return float(campaign["daily_budget_usd"])
    if campaign.get("daily_budget") is not None:
        return float(campaign["daily_budget"])
    return None


async def upsert_campaigns(
    account_uuid: str,
    campaigns: list[dict],
    platform: str,
    account_external_id: str | None = None,
) -> dict[str, str]:
    """Faz upsert das campanhas no Supabase.

    Retorna dict {campaign_id_externo: uuid_interno} para uso imediato no ciclo.
    Falhas são logadas e retornam mapa parcial/vazio — não interrompem o ciclo.
    """
    if not account_uuid or not campaigns:
        return {}

    id_map: dict[str, str] = {}
    created = 0
    updated = 0

    for campaign in campaigns:
        external_id = str(campaign.get("campaign_id") or "").strip()
        if not external_id:
            continue

        row: dict[str, Any] = {
            "account_id": account_uuid,
            "campaign_id": external_id,
            "name": campaign.get("name") or external_id,
            "platform": platform,
            "status": _normalize_status(campaign.get("status"), platform),
            "objective": campaign.get("objective"),
            "daily_budget": _daily_budget(campaign),
            "updated_at": datetime.utcnow().isoformat(),
        }

        existing = (
            supabase.table("campaigns")
            .select("id")
            .eq("account_id", account_uuid)
            .eq("campaign_id", external_id)
            .limit(1)
            .execute()
        )

        if existing.data:
            internal_id = existing.data[0]["id"]
            update_fields = {
                k: v
                for k, v in row.items()
                if k not in ("account_id", "campaign_id") and v is not None
            }
            supabase.table("campaigns").update(update_fields).eq("id", internal_id).execute()
            id_map[external_id] = internal_id
            updated += 1
        else:
            insert_result = supabase.table("campaigns").insert(row).execute()
            if insert_result.data:
                id_map[external_id] = insert_result.data[0]["id"]
                created += 1

    log.info(
        "campaign_registry.upsert",
        created=created,
        updated=updated,
        account_id=account_external_id or account_uuid,
        total=len(id_map),
    )
    return id_map


async def register_campaigns_safe(
    account_uuid: str,
    campaigns: list[dict],
    platform: str,
    account_external_id: str | None = None,
) -> dict[str, str]:
    """Wrapper com try/except para não quebrar o ciclo do agente."""
    try:
        id_map = await upsert_campaigns(
            account_uuid,
            campaigns,
            platform,
            account_external_id=account_external_id,
        )
        return merge_campaign_id_map(id_map)
    except Exception as exc:
        log.warning(
            "campaign_registry.upsert_failed",
            account_id=account_external_id or account_uuid,
            platform=platform,
            error=str(exc),
        )
        return get_campaign_id_map()


def _is_invalid_uuid(value: Any) -> bool:
    """Retorna True para qualquer valor que não seja UUID v4 válido."""
    if not value:
        return True
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return True
    return parsed.version != 4


def get_campaign_real_roas(campaign_uuid: str) -> dict:
    """
    Busca ROAS real baseado em deals fechados no CRM.
    Delega para BigQuery com fallback Supabase; retorna chaves legadas
    (revenue_closed) para compatibilidade com callers existentes.
    """
    from agent.tools.bigquery_attribution import get_campaign_real_roas as _bq_roas

    data = _bq_roas(campaign_uuid)
    return {
        "revenue_closed": data.get("revenue_real", 0),
        "leads_total": data.get("leads_total", 0),
        "deals_closed": data.get("deals_closed", 0),
    }
