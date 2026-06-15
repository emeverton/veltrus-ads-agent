"""Google Ads Agent — lista e monitora campanhas do customer_id configurado via env.

Chamado por agent/run.py quando GOOGLE_ADS_CUSTOMER_ID está presente.
Separado do grafo LangGraph principal para permitir execução independente.
"""
from __future__ import annotations

from typing import Any

import structlog

from agent.config import settings
from agent.tools import google_ads

log = structlog.get_logger(__name__)


async def run_google_agent(
    customer_id: str,
    credentials: dict[str, Any],
) -> list[dict[str, Any]]:
    """Lista campanhas ativas do Google Ads para o customer_id informado.

    Retorna lista de campanhas ou lista vazia em caso de erro.
    """
    log.info("google.list_campaigns.start", customer_id=customer_id)

    try:
        campaigns = await google_ads.get_campaigns(customer_id, credentials)
    except Exception:
        log.exception("google.list_campaigns.error", customer_id=customer_id)
        return []

    log.info(
        "google.list_campaigns.done",
        customer_id=customer_id,
        total=len(campaigns),
    )
    return campaigns


def build_credentials_from_settings() -> dict[str, Any]:
    """Monta o dict de credenciais Google Ads a partir das configurações globais."""
    return {
        "client_id": settings.google_ads_client_id,
        "client_secret": settings.google_ads_client_secret,
        "refresh_token": settings.google_ads_refresh_token,
        "login_customer_id": settings.google_ads_login_customer_id or None,
    }
