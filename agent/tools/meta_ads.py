"""Ferramentas Meta Ads via facebook-business SDK v21.0."""
from __future__ import annotations

import time
from datetime import date
from typing import Any

import structlog
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.user import User
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError

from agent.config import settings

log = structlog.get_logger(__name__)

_API_VERSION = settings.meta_api_version  # "v21.0"

# ---------------------------------------------------------------------------
# Campos de insights que o agente consome
# ---------------------------------------------------------------------------
_INSIGHT_FIELDS = [
    "spend",
    "impressions",
    "clicks",
    "actions",           # inclui conversions (purchase, lead, etc.)
    "action_values",     # receita por ação → base do ROAS
    "cost_per_action_type",
    "ctr",
]

_CONVERSION_ACTION_TYPES = {"purchase", "lead", "complete_registration", "subscribe"}

# ---------------------------------------------------------------------------
# Retry com backoff exponencial para rate-limit (código 17 e 613)
# ---------------------------------------------------------------------------
_RATE_LIMIT_CODES = {17, 613, 80004}
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # segundos


def _init_api(access_token: str) -> None:
    FacebookAdsApi.init(access_token=access_token, api_version=_API_VERSION)


def _retry(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Executa *fn* com retry exponencial em rate-limit errors."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except FacebookRequestError as exc:
            code = exc.api_error_code()
            if code in _RATE_LIMIT_CODES and attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                log.warning(
                    "meta.rate_limit",
                    error_code=code,
                    attempt=attempt,
                    retry_in_seconds=wait,
                )
                time.sleep(wait)
            else:
                raise
    # nunca atingido, mas satisfaz o type checker
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# 1. get_ad_accounts
# ---------------------------------------------------------------------------
async def get_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """Lista todas as contas de ads acessíveis pelo token do usuário."""
    log.info("meta.get_ad_accounts.start")
    _init_api(access_token)

    fields = ["id", "name", "account_status", "currency", "timezone_name"]

    raw: list[Any] = _retry(
        User(fbid="me").get_ad_accounts,
        fields=fields,
    )

    accounts = [dict(a) for a in raw]
    log.info("meta.get_ad_accounts.done", total=len(accounts))
    return accounts


# ---------------------------------------------------------------------------
# 1b. list_campaigns
# ---------------------------------------------------------------------------
async def list_campaigns(account_id: str, access_token: str) -> list[dict[str, Any]]:
    """Lista campanhas ativas e pausadas de uma conta Meta Ads."""
    log.info("meta.list_campaigns.start", account_id=account_id)
    _init_api(access_token)

    clean_id = account_id.replace("act_", "")
    fields = ["id", "name", "status", "effective_status", "daily_budget", "objective"]

    raw: list[Any] = _retry(
        AdAccount(f"act_{clean_id}").get_campaigns,
        fields=fields,
        params={"effective_status": ["ACTIVE", "PAUSED"]},
    )

    campaigns = []
    for c in raw:
        d = dict(c)
        campaigns.append({
            "campaign_id": d.get("id", ""),
            "name": d.get("name", ""),
            "status": d.get("status", ""),
            "effective_status": d.get("effective_status", ""),
            "daily_budget_usd": float(d.get("daily_budget", 0)) / 100,
            "objective": d.get("objective", ""),
        })

    log.info("meta.list_campaigns.done", account_id=account_id, total=len(campaigns))
    return campaigns


# ---------------------------------------------------------------------------
# 2. get_campaign_insights
# ---------------------------------------------------------------------------
async def get_campaign_insights(
    account_id: str,
    campaign_id: str,
    date_start: date,
    date_end: date,
    access_token: str,
) -> dict[str, Any]:
    """Retorna métricas agregadas de uma campanha no período informado.

    Métricas retornadas: spend, impressions, clicks, conversions, cpa, roas, ctr.
    """
    log.info(
        "meta.get_campaign_insights.start",
        account_id=account_id,
        campaign_id=campaign_id,
        date_start=str(date_start),
        date_end=str(date_end),
    )
    _init_api(access_token)

    params = {
        "level": "campaign",
        "filtering": [{"field": "campaign.id", "operator": "EQUAL", "value": campaign_id}],
        "time_range": {
            "since": str(date_start),
            "until": str(date_end),
        },
        "time_increment": "all_days",  # agrega o período inteiro em uma linha
    }

    raw_list: list[Any] = _retry(
        AdAccount(f"act_{account_id}").get_insights,
        fields=_INSIGHT_FIELDS,
        params=params,
    )

    if not raw_list:
        log.warning(
            "meta.get_campaign_insights.empty",
            account_id=account_id,
            campaign_id=campaign_id,
        )
        return _empty_metrics(campaign_id)

    raw = dict(raw_list[0])

    spend = float(raw.get("spend") or 0)
    impressions = int(raw.get("impressions") or 0)
    clicks = int(raw.get("clicks") or 0)
    ctr = float(raw.get("ctr") or 0)

    conversions = _sum_actions(raw.get("actions", []), _CONVERSION_ACTION_TYPES)
    revenue = _sum_actions(raw.get("action_values", []), _CONVERSION_ACTION_TYPES)

    cpa = (spend / conversions) if conversions > 0 else None
    roas = (revenue / spend) if spend > 0 else None

    metrics = {
        "campaign_id": campaign_id,
        "spend": round(spend, 4),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": round(conversions, 4),
        "cpa": round(cpa, 4) if cpa is not None else None,
        "roas": round(roas, 4) if roas is not None else None,
        "ctr": round(ctr, 6),
        "raw_payload": raw,
    }

    log.info(
        "meta.get_campaign_insights.done",
        campaign_id=campaign_id,
        spend=metrics["spend"],
        roas=metrics["roas"],
        cpa=metrics["cpa"],
    )
    return metrics


def _sum_actions(actions: list[dict[str, Any]], types: set[str]) -> float:
    return sum(
        float(a.get("value", 0))
        for a in actions
        if a.get("action_type") in types
    )


def _empty_metrics(campaign_id: str) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "spend": 0.0,
        "impressions": 0,
        "clicks": 0,
        "conversions": 0.0,
        "cpa": None,
        "roas": None,
        "ctr": 0.0,
        "raw_payload": {},
    }


# ---------------------------------------------------------------------------
# 3. update_campaign_budget
# ---------------------------------------------------------------------------
async def update_campaign_budget(
    campaign_id: str,
    daily_budget: float,
    access_token: str,
) -> dict[str, Any]:
    """Atualiza o budget diário de uma campanha (valor em centavos de USD internamente)."""
    log.info(
        "meta.update_campaign_budget.start",
        campaign_id=campaign_id,
        daily_budget_usd=daily_budget,
    )
    _init_api(access_token)

    # Meta Ads API recebe budget em centavos da moeda da conta
    budget_cents = int(daily_budget * 100)

    campaign = Campaign(campaign_id)
    result = _retry(
        campaign.remote_update,
        params={"daily_budget": budget_cents},
    )

    log.info(
        "meta.update_campaign_budget.done",
        campaign_id=campaign_id,
        daily_budget_usd=daily_budget,
        daily_budget_cents=budget_cents,
    )
    return {"campaign_id": campaign_id, "daily_budget_usd": daily_budget, "result": result}


# ---------------------------------------------------------------------------
# 4. pause_campaign
# ---------------------------------------------------------------------------
async def pause_campaign(campaign_id: str, access_token: str) -> dict[str, Any]:
    """Pausa uma campanha ativa."""
    log.info("meta.pause_campaign.start", campaign_id=campaign_id)
    _init_api(access_token)

    campaign = Campaign(campaign_id)
    result = _retry(
        campaign.remote_update,
        params={"status": Campaign.Status.paused},
    )

    log.info("meta.pause_campaign.done", campaign_id=campaign_id)
    return {"campaign_id": campaign_id, "status": "paused", "result": result}


# ---------------------------------------------------------------------------
# 5. activate_campaign
# ---------------------------------------------------------------------------
async def activate_campaign(campaign_id: str, access_token: str) -> dict[str, Any]:
    """Ativa (retoma) uma campanha pausada."""
    log.info("meta.activate_campaign.start", campaign_id=campaign_id)
    _init_api(access_token)

    campaign = Campaign(campaign_id)
    result = _retry(
        campaign.remote_update,
        params={"status": Campaign.Status.active},
    )

    log.info("meta.activate_campaign.done", campaign_id=campaign_id)
    return {"campaign_id": campaign_id, "status": "active", "result": result}
