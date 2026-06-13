"""Carrega guardrails e configuração por cliente do Supabase."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from agent.config import settings
from agent.guardrails import GuardrailsConfig
from agent.tools.supabase_client import supabase


def _decimal(value: Any, fallback: Decimal) -> Decimal:
    if value is None:
        return fallback
    return Decimal(str(value))


def load_client_config(client: dict[str, Any]) -> dict[str, Any]:
    """
    Lê guardrails do registro clients.
    Fallback para variáveis de ambiente quando colunas não existirem ou forem null.
    """
    env_daily_brl = Decimal(str(os.getenv("AGENT_MAX_DAILY_SPEND_BRL", "200")))
    env_max_pct = int(os.getenv("AGENT_MAX_BUDGET_CHANGE_PCT", str(settings.agent_max_budget_change_pct)))
    env_min_roas = Decimal(str(os.getenv("AGENT_MIN_ROAS", "2.0")))
    env_max_cpa = Decimal(str(os.getenv("AGENT_MAX_CPA_BRL", "100.0")))

    daily_budget_brl = client.get("daily_budget_brl")
    if daily_budget_brl is None and settings.agent_max_daily_spend_usd:
        # Fallback legado USD → BRL com taxa configurável
        rate = Decimal(str(os.getenv("AGENT_USD_BRL_RATE", "5.0")))
        daily_budget_brl = float(Decimal(str(settings.agent_max_daily_spend_usd)) * rate)
    if daily_budget_brl is None:
        daily_budget_brl = float(env_daily_brl)

    autonomous = client.get("autonomous_mode")
    if autonomous is None:
        autonomous = settings.agent_autonomous_mode

    return {
        "client_id": client.get("id"),
        "daily_budget_brl": float(daily_budget_brl),
        "max_budget_change_pct": client.get("max_budget_change_pct") or env_max_pct,
        "min_roas": float(client.get("min_roas") or env_min_roas),
        "max_cpa_brl": float(client.get("max_cpa_brl") or env_max_cpa),
        "cycle_interval_minutes": client.get("cycle_interval_minutes") or settings.agent_cycle_interval_minutes,
        "autonomous_mode": bool(autonomous),
        "meta_ad_account_id": client.get("meta_ad_account_id"),
        "google_ads_customer_id": client.get("google_ads_customer_id"),
    }


def guardrails_config_from_client(client_config: dict[str, Any]) -> GuardrailsConfig:
    return GuardrailsConfig(
        daily_budget_brl=_decimal(client_config.get("daily_budget_brl"), Decimal("200")),
        max_budget_change_pct=int(client_config.get("max_budget_change_pct", 20)),
        min_roas=_decimal(client_config.get("min_roas"), Decimal("2.0")),
        max_cpa_brl=_decimal(client_config.get("max_cpa_brl"), Decimal("100.0")),
    )


def compute_total_daily_spend(campaigns_analyzed: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for camp in campaigns_analyzed:
        spend = camp.get("last_spend_usd") or camp.get("daily_budget") or 0
        total += Decimal(str(spend))
    return total


def find_campaign_budget_brl(
    decision: dict[str, Any],
    campaigns_analyzed: list[dict[str, Any]],
    *,
    usd_brl_rate: Decimal = Decimal("5.0"),
) -> Decimal:
    campaign_uuid = decision.get("campaign_uuid")
    camp = next(
        (c for c in campaigns_analyzed if c.get("campaign_uuid") == campaign_uuid),
        {},
    )
    if camp.get("daily_budget_brl") is not None:
        return Decimal(str(camp["daily_budget_brl"]))
    if camp.get("daily_budget") is not None:
        return Decimal(str(camp["daily_budget"])) * usd_brl_rate
    if camp.get("last_spend_usd") is not None:
        return Decimal(str(camp["last_spend_usd"])) * usd_brl_rate
    return Decimal("0")
