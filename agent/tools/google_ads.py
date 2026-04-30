"""Ferramentas Google Ads via google-ads-python client library."""
from __future__ import annotations

import time
from datetime import date
from typing import Any

import grpc
import structlog
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from agent.config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Retry com backoff exponencial para rate-limit e erros transientes
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # segundos
_RETRYABLE_STATUS_CODES = {grpc.StatusCode.RESOURCE_EXHAUSTED, grpc.StatusCode.UNAVAILABLE}


def _build_client(credentials: dict[str, Any]) -> GoogleAdsClient:
    """Constrói o GoogleAdsClient mesclando credenciais OAuth com o developer_token do settings."""
    config = {
        "use_proto_plus": True,
        "developer_token": settings.google_ads_developer_token,
        **credentials,  # client_id, client_secret, refresh_token, login_customer_id (opcional)
    }
    return GoogleAdsClient.load_from_dict(config)


def _retry(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Executa *fn* com retry exponencial em RESOURCE_EXHAUSTED e UNAVAILABLE."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except GoogleAdsException as exc:
            status_code = exc.error.code()
            if status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                log.warning(
                    "google.rate_limit",
                    status_code=status_code.name,
                    attempt=attempt,
                    retry_in_seconds=wait,
                )
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# 1. get_campaigns
# ---------------------------------------------------------------------------
async def get_campaigns(
    customer_id: str,
    credentials: dict[str, Any],
) -> list[dict[str, Any]]:
    """Lista campanhas não-removidas com nome, status e budget diário."""
    log.info("google.get_campaigns.start", customer_id=customer_id)
    client = _build_client(credentials)
    ga_service = client.get_service("GoogleAdsService")

    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign_budget.id,
            campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.name
    """

    rows = list(_retry(ga_service.search, customer_id=customer_id, query=query))

    campaigns = [
        {
            "campaign_id": str(row.campaign.id),
            "name": row.campaign.name,
            "status": row.campaign.status.name,           # "ENABLED" | "PAUSED"
            "campaign_budget_id": str(row.campaign_budget.id),
            "daily_budget_usd": row.campaign_budget.amount_micros / 1_000_000,
        }
        for row in rows
    ]

    log.info("google.get_campaigns.done", customer_id=customer_id, total=len(campaigns))
    return campaigns


# ---------------------------------------------------------------------------
# 2. get_campaign_insights
# ---------------------------------------------------------------------------
async def get_campaign_insights(
    customer_id: str,
    campaign_id: str,
    date_start: date,
    date_end: date,
    credentials: dict[str, Any],
) -> dict[str, Any]:
    """Retorna métricas agregadas de uma campanha no período informado.

    Métricas retornadas: spend, impressions, clicks, conversions, cpa, roas, ctr.
    campaign_id é o ID numérico da campanha (sem prefixo de resource name).
    """
    log.info(
        "google.get_campaign_insights.start",
        customer_id=customer_id,
        campaign_id=campaign_id,
        date_start=str(date_start),
        date_end=str(date_end),
    )
    client = _build_client(credentials)
    ga_service = client.get_service("GoogleAdsService")

    # segments.date no WHERE (sem SELECT) agrega os dados do período em uma linha.
    # campaign_id é sempre numérico — sem risco de injeção GAQL.
    query = f"""
        SELECT
            campaign.id,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM campaign
        WHERE campaign.id = {campaign_id}
          AND segments.date BETWEEN '{date_start}' AND '{date_end}'
    """

    rows = list(_retry(ga_service.search, customer_id=customer_id, query=query))

    if not rows:
        log.warning(
            "google.get_campaign_insights.empty",
            customer_id=customer_id,
            campaign_id=campaign_id,
        )
        return _empty_metrics(campaign_id)

    # Agrega manualmente para garantir consistência mesmo se a API retornar >1 linha
    total_cost_micros = sum(r.metrics.cost_micros for r in rows)
    total_impressions = sum(r.metrics.impressions for r in rows)
    total_clicks = sum(r.metrics.clicks for r in rows)
    total_conversions = sum(r.metrics.conversions for r in rows)
    total_revenue = sum(r.metrics.conversions_value for r in rows)

    spend = total_cost_micros / 1_000_000
    cpa = (spend / total_conversions) if total_conversions > 0 else None
    roas = (total_revenue / spend) if spend > 0 else None
    ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0.0

    metrics = {
        "campaign_id": campaign_id,
        "spend": round(spend, 4),
        "impressions": total_impressions,
        "clicks": total_clicks,
        "conversions": round(total_conversions, 4),
        "cpa": round(cpa, 4) if cpa is not None else None,
        "roas": round(roas, 4) if roas is not None else None,
        "ctr": round(ctr, 6),
        "raw_payload": {
            "cost_micros": total_cost_micros,
            "impressions": total_impressions,
            "clicks": total_clicks,
            "conversions": total_conversions,
            "conversions_value": total_revenue,
            "row_count": len(rows),
        },
    }

    log.info(
        "google.get_campaign_insights.done",
        campaign_id=campaign_id,
        spend=metrics["spend"],
        roas=metrics["roas"],
        cpa=metrics["cpa"],
    )
    return metrics


# ---------------------------------------------------------------------------
# 3. update_campaign_budget
# ---------------------------------------------------------------------------
async def update_campaign_budget(
    customer_id: str,
    campaign_budget_id: str,
    amount_micros: int,
    credentials: dict[str, Any],
) -> dict[str, Any]:
    """Atualiza o budget diário de uma campanha.

    amount_micros: valor em micros (USD * 1_000_000). Ex: $10 → 10_000_000.
    campaign_budget_id: ID do CampaignBudget (obtido via get_campaigns).
    """
    log.info(
        "google.update_campaign_budget.start",
        customer_id=customer_id,
        campaign_budget_id=campaign_budget_id,
        amount_micros=amount_micros,
        amount_usd=amount_micros / 1_000_000,
    )
    client = _build_client(credentials)
    budget_service = client.get_service("CampaignBudgetService")

    operation = client.get_type("CampaignBudgetOperation")
    budget = operation.update
    budget.resource_name = budget_service.campaign_budget_path(customer_id, campaign_budget_id)
    budget.amount_micros = amount_micros
    operation.update_mask.paths.append("amount_micros")

    _retry(
        budget_service.mutate_campaign_budgets,
        customer_id=customer_id,
        operations=[operation],
    )

    log.info(
        "google.update_campaign_budget.done",
        customer_id=customer_id,
        campaign_budget_id=campaign_budget_id,
        amount_usd=amount_micros / 1_000_000,
    )
    return {
        "customer_id": customer_id,
        "campaign_budget_id": campaign_budget_id,
        "amount_micros": amount_micros,
        "amount_usd": amount_micros / 1_000_000,
    }


# ---------------------------------------------------------------------------
# 4. pause_campaign
# ---------------------------------------------------------------------------
async def pause_campaign(
    customer_id: str,
    campaign_id: str,
    credentials: dict[str, Any],
) -> dict[str, Any]:
    """Pausa uma campanha ativa."""
    log.info("google.pause_campaign.start", customer_id=customer_id, campaign_id=campaign_id)
    client = _build_client(credentials)
    campaign_service = client.get_service("CampaignService")

    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    operation.update_mask.paths.append("status")

    _retry(
        campaign_service.mutate_campaigns,
        customer_id=customer_id,
        operations=[operation],
    )

    log.info("google.pause_campaign.done", customer_id=customer_id, campaign_id=campaign_id)
    return {"customer_id": customer_id, "campaign_id": campaign_id, "status": "paused"}


# ---------------------------------------------------------------------------
# 5. activate_campaign
# ---------------------------------------------------------------------------
async def activate_campaign(
    customer_id: str,
    campaign_id: str,
    credentials: dict[str, Any],
) -> dict[str, Any]:
    """Ativa (retoma) uma campanha pausada."""
    log.info("google.activate_campaign.start", customer_id=customer_id, campaign_id=campaign_id)
    client = _build_client(credentials)
    campaign_service = client.get_service("CampaignService")

    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)
    campaign.status = client.enums.CampaignStatusEnum.ENABLED
    operation.update_mask.paths.append("status")

    _retry(
        campaign_service.mutate_campaigns,
        customer_id=customer_id,
        operations=[operation],
    )

    log.info("google.activate_campaign.done", customer_id=customer_id, campaign_id=campaign_id)
    return {"customer_id": customer_id, "campaign_id": campaign_id, "status": "active"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
