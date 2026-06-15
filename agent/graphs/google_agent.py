"""Google Ads agent entrypoint."""
from __future__ import annotations

import structlog

from agent.config import settings
from agent.tools import google_ads

log = structlog.get_logger(__name__)


def _google_ads_credentials() -> dict:
    """Monta credenciais Google Ads a partir do .env."""
    return {
        "client_id": settings.google_ads_client_id,
        "client_secret": settings.google_ads_client_secret,
        "refresh_token": settings.google_ads_refresh_token,
        "login_customer_id": settings.google_ads_login_customer_id or None,
    }


async def run_google_agent() -> None:
    """Executa a coleta Google Ads quando GOOGLE_ADS_CUSTOMER_ID está configurado."""
    customer_id = settings.google_ads_customer_id.strip()
    if not customer_id:
        return

    try:
        campaigns = await google_ads.get_campaigns(customer_id, _google_ads_credentials())
        log.info("run.google_agent.done", customer_id=customer_id, campaigns=len(campaigns))
    except Exception:
        log.exception("run.google_agent.error", customer_id=customer_id)
