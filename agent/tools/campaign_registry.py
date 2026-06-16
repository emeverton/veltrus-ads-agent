"""Registro idempotente de campanhas externas no Supabase."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)

_VALID_PLATFORMS = {"meta", "google"}


async def upsert_campaigns(
    account_uuid: str,
    campaigns: list[dict],
    platform: str,
) -> dict[str, str]:
    """
    Faz upsert das campanhas no Supabase.
    Retorna dict {campaign_id_externo: uuid_interno} para uso imediato no ciclo.

    O schema atual não declara uma constraint única para ON CONFLICT. Por isso o
    upsert é explícito: busca por (account_id, campaign_id, platform), atualiza
    quando existe e insere com UUID novo quando não existe.
    """
    campaign_id_map: dict[str, str] = {}
    normalized_platform = str(platform or "").strip().lower()
    if normalized_platform not in _VALID_PLATFORMS:
        log.warning(
            "campaign_registry.skip",
            reason="invalid_platform",
            platform=platform,
            account_uuid=account_uuid,
        )
        return campaign_id_map

    created = 0
    updated = 0
    skipped = 0

    try:
        for campaign in campaigns or []:
            external_id = _external_campaign_id(campaign)
            if not external_id:
                skipped += 1
                log.warning(
                    "campaign_registry.skip",
                    reason="missing_campaign_id",
                    account_uuid=account_uuid,
                    platform=normalized_platform,
                    campaign=campaign,
                )
                continue

            row = _campaign_row(account_uuid, campaign, normalized_platform)
            existing_id = _fetch_existing_campaign_id(
                account_uuid,
                external_id,
                normalized_platform,
            )

            if existing_id:
                _update_campaign(existing_id, row)
                campaign_id_map[external_id] = existing_id
                updated += 1
                continue

            internal_id = str(uuid.uuid4())
            inserted = _insert_campaign(
                {
                    "id": internal_id,
                    "created_at": row["updated_at"],
                    **row,
                }
            )
            campaign_id_map[external_id] = inserted or internal_id
            created += 1
    except Exception as exc:  # pragma: no cover - rede/DB
        log.exception(
            "campaign_registry.upsert_failed",
            account_uuid=account_uuid,
            platform=normalized_platform,
            error=str(exc),
        )
        return campaign_id_map

    log.info(
        "campaign_registry.upsert",
        created=created,
        updated=updated,
        skipped=skipped,
        account_id=account_uuid,
        account_uuid=account_uuid,
        platform=normalized_platform,
    )
    return campaign_id_map


def _external_campaign_id(campaign: dict[str, Any]) -> str:
    return str(campaign.get("campaign_id") or campaign.get("id") or "").strip()


def _campaign_row(account_uuid: str, campaign: dict[str, Any], platform: str) -> dict[str, Any]:
    external_id = _external_campaign_id(campaign)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "account_id": account_uuid,
        "campaign_id": external_id,
        "name": str(campaign.get("name") or "").strip(),
        "platform": platform,
        "status": str(
            campaign.get("status")
            or campaign.get("effective_status")
            or ""
        ).strip(),
        "objective": _optional_string(campaign.get("objective")),
        "daily_budget": _daily_budget(campaign),
        "updated_at": now,
    }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _daily_budget(campaign: dict[str, Any]) -> float | None:
    raw = campaign.get("daily_budget_usd")
    if raw is None:
        raw = campaign.get("daily_budget")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _fetch_existing_campaign_id(
    account_uuid: str,
    external_id: str,
    platform: str,
) -> str | None:
    result = (
        supabase.table("campaigns")
        .select("id")
        .eq("account_id", account_uuid)
        .eq("campaign_id", external_id)
        .eq("platform", platform)
        .maybe_single()
        .execute()
    )
    data = result.data or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    return str(data.get("id") or "").strip() or None


def _insert_campaign(row: dict[str, Any]) -> str | None:
    result = supabase.table("campaigns").insert(row).execute()
    data = result.data or []
    if isinstance(data, dict):
        return str(data.get("id") or "").strip() or None
    if data:
        return str(data[0].get("id") or "").strip() or None
    return None


def _update_campaign(internal_id: str, row: dict[str, Any]) -> None:
    supabase.table("campaigns").update(row).eq("id", internal_id).execute()
