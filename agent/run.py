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
from agent.graphs.google_agent import build_credentials_from_settings, run_google_agent
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)


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

    Ao final, executa google_agent para o GOOGLE_ADS_CUSTOMER_ID global (se configurado),
    independentemente de haver contas no Supabase.
    """
    started_at = datetime.utcnow()
    log.info("run.cycle.start", started_at=started_at.isoformat())

    result = (
        supabase.table("ad_accounts")
        .select("*, clients(*)")
        .eq("active", True)
        .execute()
    )
    rows = result.data or []

    if not rows:
        log.warning("run.cycle.no_active_accounts")
    else:
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

    # Executa google_agent direto via GOOGLE_ADS_CUSTOMER_ID (env var) se configurado.
    # Roda independentemente do número de contas no Supabase — útil para MCC / customer IDs globais.
    if settings.google_ads_customer_id:
        log.info("run.google_agent.start", customer_id=settings.google_ads_customer_id)
        try:
            await run_google_agent(
                settings.google_ads_customer_id,
                build_credentials_from_settings(),
            )
        except Exception:
            log.exception(
                "run.google_agent.error",
                customer_id=settings.google_ads_customer_id,
            )


if __name__ == "__main__":
    asyncio.run(run_all_accounts())
