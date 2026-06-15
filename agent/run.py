"""
Ponto de entrada do agente — executa o grafo para todas as contas de anúncios ativas.

Uso direto:
    python -m agent.run

Via APScheduler (agent.main): importar e agendar run_all_accounts().
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from agent.config import settings
from agent.graph import AgentState, compiled_graph
from agent.tools import google_ads
from agent.tools.supabase_client import supabase

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


async def run_account(account: dict, client: dict) -> None:
    """Executa o grafo completo para uma única conta de anúncios."""
    account_id = account.get("account_id", account.get("id"))
    platform = account.get("platform")

    log.info("run.account.start", account_id=account_id, platform=platform)

    initial_state: AgentState = {
        "account": account,
        "client": client,
        "campaigns_analyzed": [],
        "anomalies": [],
        "decision": {},
        "memory_context": [],
        "risk_level": "",
        "risk_reasoning": "",
        "execution_result": {},
    }

    try:
        await compiled_graph.ainvoke(initial_state)
        log.info("run.account.done", account_id=account_id, platform=platform)
    except Exception:
        log.exception("run.account.error", account_id=account_id, platform=platform)


async def run_all_accounts() -> None:
    """
    Busca todas as contas de anúncios ativas com cliente ativo e executa o grafo
    para cada uma sequencialmente.

    Sequencial (não paralelo) para evitar sobrecarga simultânea nas APIs de ads
    e na cota do LLM. Paralelizar por plataforma é uma evolução futura segura.
    """
    started_at = datetime.utcnow()
    log.info("run.cycle.start", started_at=started_at.isoformat())

    await run_google_agent()

    result = (
        supabase.table("ad_accounts")
        .select("*, clients(*)")
        .eq("active", True)
        .execute()
    )
    rows = result.data or []

    if not rows:
        log.warning("run.cycle.no_active_accounts")
        return

    # Filtra contas cujo cliente também está ativo
    accounts_to_run = [
        row for row in rows
        if (row.get("clients") or {}).get("active", True)
    ]

    log.info("run.cycle.accounts_found", total=len(rows), eligible=len(accounts_to_run))

    errors = 0
    for row in accounts_to_run:
        client = row.pop("clients", {}) or {}
        await run_account(account=row, client=client)

    elapsed = (datetime.utcnow() - started_at).total_seconds()
    log.info(
        "run.cycle.done",
        accounts_processed=len(accounts_to_run),
        errors=errors,
        elapsed_seconds=round(elapsed, 1),
    )


if __name__ == "__main__":
    asyncio.run(run_all_accounts())
