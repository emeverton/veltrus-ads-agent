"""
api/routers/decisions.py — Aprovação humana de decisões do agente

GET  /decisions              lista decisões pendentes com dados da campanha
PATCH /decisions/{id}/approve aprova e executa via Meta/Google API
PATCH /decisions/{id}/reject  rejeita com motivo (não executa)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel

from agent.config import settings
from agent.tools import google_ads, meta_ads
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/decisions", tags=["decisions"])

# ---------------------------------------------------------------------------
# Auth — X-API-Key header
# ---------------------------------------------------------------------------
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def _require_api_key(key: str = Security(_api_key_header)) -> str:
    if key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ApproveRequest(BaseModel):
    approved_by: str = "human"


class RejectRequest(BaseModel):
    rejected_by: str = "human"
    reason: str


class DecisionOut(BaseModel):
    id: str
    action_type: str
    reasoning: str
    payload: dict[str, Any]
    executed: bool
    approved_by: str | None
    approved_at: str | None
    created_at: str
    campaign: dict[str, Any]
    ad_account: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_decision(decision_id: str) -> dict[str, Any]:
    resp = (
        supabase.table("agent_decisions")
        .select(
            "*, campaigns(id, name, campaign_id, platform, daily_budget, "
            "ad_accounts(id, account_id, platform, token))"
        )
        .eq("id", decision_id)
        .maybe_single()
        .execute()
    )
    data = resp.data if resp is not None else None
    if not data:
        raise HTTPException(status_code=404, detail=f"Decision {decision_id} not found")
    return data


def _assert_pending(decision: dict[str, Any]) -> None:
    """Garante que a decisão ainda não foi processada."""
    if decision.get("executed"):
        raise HTTPException(status_code=409, detail="Decision already executed")
    if decision.get("approved_at") is not None:
        raise HTTPException(status_code=409, detail="Decision already reviewed (rejected)")


async def _execute_action(
    action_type: str,
    payload: dict[str, Any],
    campaign: dict[str, Any],
    ad_account: dict[str, Any],
) -> dict[str, Any]:
    """Despacha a ação para a plataforma correta e retorna o resultado da API."""
    platform             = campaign.get("platform") or ad_account.get("platform", "meta")
    campaign_external_id = campaign.get("campaign_id", "")
    account_external_id  = ad_account.get("account_id", "")
    token                = ad_account.get("token", "")

    log.info(
        "decisions.execute_action",
        action_type=action_type,
        platform=platform,
        campaign_external_id=campaign_external_id,
    )

    if platform == "meta":
        if action_type == "pause_campaign":
            return await meta_ads.pause_campaign(campaign_external_id, token)

        if action_type == "activate_campaign":
            return await meta_ads.activate_campaign(campaign_external_id, token)

        if action_type in ("budget_increase", "budget_decrease"):
            budget = payload.get("daily_budget_usd") or payload.get("params", {}).get("daily_budget_usd")
            if budget is None:
                raise HTTPException(
                    status_code=422,
                    detail="payload.daily_budget_usd required for budget actions",
                )
            return await meta_ads.update_campaign_budget(campaign_external_id, float(budget), token)

    elif platform == "google":
        credentials = {
            "client_id":     settings.google_ads_client_id,
            "client_secret": settings.google_ads_client_secret,
            "refresh_token": token,
            "login_customer_id": settings.google_ads_login_customer_id or None,
        }
        customer_id = payload.get("customer_id") or account_external_id

        if action_type == "pause_campaign":
            return await google_ads.pause_campaign(customer_id, campaign_external_id, credentials)

        if action_type == "activate_campaign":
            return await google_ads.activate_campaign(customer_id, campaign_external_id, credentials)

        if action_type in ("budget_increase", "budget_decrease"):
            budget_id = payload.get("campaign_budget_id")
            amount_micros = payload.get("amount_micros")
            if not budget_id or amount_micros is None:
                raise HTTPException(
                    status_code=422,
                    detail="payload.campaign_budget_id and payload.amount_micros required",
                )
            return await google_ads.update_campaign_budget(
                customer_id, budget_id, int(amount_micros), credentials
            )

    raise HTTPException(
        status_code=422,
        detail=f"Unsupported platform '{platform}' or action_type '{action_type}'",
    )


def _format_decision(row: dict[str, Any]) -> dict[str, Any]:
    campaign_raw = row.pop("campaigns", None) or {}

    # PostgREST retorna "belongs-to" como objeto e "has-many" como lista.
    # Se o schema cache estiver desatualizado ele pode retornar lista mesmo para
    # um relacionamento muitos-para-um — tratamos os dois casos.
    if isinstance(campaign_raw, list):
        campaign = campaign_raw[0] if campaign_raw else {}
    else:
        campaign = campaign_raw

    ad_account_raw = campaign.pop("ad_accounts", None) if isinstance(campaign, dict) else None
    if isinstance(ad_account_raw, list):
        ad_account: dict[str, Any] = ad_account_raw[0] if ad_account_raw else {}
    else:
        ad_account = ad_account_raw or {}

    ad_account.pop("token", None)
    return {**row, "campaign": campaign, "ad_account": ad_account}


# ---------------------------------------------------------------------------
# GET /decisions
# ---------------------------------------------------------------------------
@router.get("", response_model=list[DecisionOut])
async def list_pending_decisions(
    _key: str = Depends(_require_api_key),
) -> list[dict[str, Any]]:
    """Lista decisões pendentes de aprovação humana (executed=false, não rejeitadas)."""
    try:
        resp = (
            supabase.table("agent_decisions")
            .select(
                "*, campaigns(id, name, campaign_id, platform, daily_budget, "
                "ad_accounts(id, account_id, platform))"
            )
            .eq("executed", False)
            .is_("approved_at", "null")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        log.error("decisions.list_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Database query failed: {exc}") from exc

    return [_format_decision(row) for row in (resp.data or [])]


# ---------------------------------------------------------------------------
# PATCH /decisions/{id}/approve
# ---------------------------------------------------------------------------
@router.patch("/{decision_id}/approve")
async def approve_decision(
    decision_id: str,
    body: ApproveRequest,
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Aprova uma decisão pendente e executa a ação via Meta/Google API."""
    row      = _fetch_decision(decision_id)
    _assert_pending(row)

    campaign   = row.get("campaigns") or {}
    ad_account = campaign.get("ad_accounts") or {}

    try:
        api_result = await _execute_action(
            action_type=row["action_type"],
            payload=row.get("payload") or {},
            campaign=campaign,
            ad_account=ad_account,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("decisions.execute_failed", decision_id=decision_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"API execution failed: {exc}") from exc

    # Atualiza o registro
    supabase.table("agent_decisions").update({
        "executed":    True,
        "approved_by": body.approved_by,
        "approved_at": _now_iso(),
        "payload":     {**(row.get("payload") or {}), "api_result": api_result},
    }).eq("id", decision_id).execute()

    log.info(
        "decisions.approved",
        decision_id=decision_id,
        action_type=row["action_type"],
        approved_by=body.approved_by,
    )
    return {
        "id":          decision_id,
        "status":      "approved",
        "action_type": row["action_type"],
        "approved_by": body.approved_by,
        "api_result":  api_result,
    }


# ---------------------------------------------------------------------------
# PATCH /decisions/{id}/reject
# ---------------------------------------------------------------------------
@router.patch("/{decision_id}/reject")
async def reject_decision(
    decision_id: str,
    body: RejectRequest,
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Rejeita uma decisão pendente. Não chama nenhuma API externa."""
    row = _fetch_decision(decision_id)
    _assert_pending(row)

    supabase.table("agent_decisions").update({
        "executed":    False,
        "approved_by": f"rejected:{body.rejected_by}",
        "approved_at": _now_iso(),
        "payload":     {
            **(row.get("payload") or {}),
            "rejection_reason": body.reason,
            "rejected_by":      body.rejected_by,
        },
    }).eq("id", decision_id).execute()

    log.info(
        "decisions.rejected",
        decision_id=decision_id,
        action_type=row["action_type"],
        rejected_by=body.rejected_by,
        reason=body.reason,
    )
    return {
        "id":          decision_id,
        "status":      "rejected",
        "action_type": row["action_type"],
        "rejected_by": body.rejected_by,
        "reason":      body.reason,
    }
