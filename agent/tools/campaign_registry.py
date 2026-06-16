"""
agent/tools/campaign_registry.py — Auto-registro de campanhas no Supabase.

Registra campanhas da Meta/Google API na tabela campaigns do Supabase,
retornando um mapa {campaign_id_externo: uuid_interno} para uso imediato
no ciclo do agente.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog

from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)


async def upsert_campaigns(
    account_uuid: str,
    campaigns: list[dict],
    platform: str,
) -> dict[str, str]:
    """Faz upsert das campanhas no Supabase.

    Retorna dict {campaign_id_externo: uuid_interno} para uso imediato
    no ciclo (fetch_daily_metrics, save_decision, save_memory).

    account_uuid: UUID interno do ad_account (ad_accounts.id)
    campaigns:    retorno de list_campaigns da API; campo campaign_id = ID externo
    platform:     'meta' | 'google'
    """
    if not campaigns:
        return {}

    # Batch-select para evitar N+1 queries — uma só requisição ao Supabase.
    try:
        existing_res = (
            supabase.table("campaigns")
            .select("id, campaign_id")
            .eq("account_id", account_uuid)
            .eq("platform", platform)
            .execute()
        )
        existing_map: dict[str, str] = {
            row["campaign_id"]: row["id"]
            for row in (existing_res.data or [])
        }
    except Exception as exc:
        log.warning("campaign_registry.fetch_existing_failed", error=str(exc))
        existing_map = {}

    result_map: dict[str, str] = {}
    created = 0
    updated = 0
    now = datetime.utcnow().isoformat()

    for campaign in campaigns:
        ext_id = str(campaign.get("campaign_id") or "").strip()
        if not ext_id:
            continue

        # Meta usa 'daily_budget' (float já convertido de centavos em meta_ads.py).
        # Google usa 'daily_budget_usd'.
        daily_budget = float(
            campaign.get("daily_budget") or campaign.get("daily_budget_usd") or 0
        )

        row: dict[str, Any] = {
            "account_id": account_uuid,
            "campaign_id": ext_id,
            "name": campaign.get("name", ""),
            "platform": platform,
            "status": campaign.get("status", ""),
            "objective": campaign.get("objective", ""),
            "daily_budget": daily_budget,
            "updated_at": now,
        }

        if ext_id in existing_map:
            internal_uuid = existing_map[ext_id]
            try:
                supabase.table("campaigns").update(row).eq("id", internal_uuid).execute()
            except Exception as exc:
                log.warning(
                    "campaign_registry.update_failed",
                    campaign_id=ext_id,
                    error=str(exc),
                )
            result_map[ext_id] = internal_uuid
            updated += 1
        else:
            new_uuid = str(uuid.uuid4())
            row["id"] = new_uuid
            row["created_at"] = now
            try:
                supabase.table("campaigns").insert(row).execute()
            except Exception as exc:
                log.warning(
                    "campaign_registry.insert_failed",
                    campaign_id=ext_id,
                    error=str(exc),
                )
            # UUID gerado fica no mapa mesmo se o insert falhou —
            # o ciclo continua sem perder o rastreio da campanha.
            result_map[ext_id] = new_uuid
            created += 1

    log.info(
        "campaign_registry.upsert",
        created=created,
        updated=updated,
        account_id=account_uuid,
        platform=platform,
    )
    return result_map
