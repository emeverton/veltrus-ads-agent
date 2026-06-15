"""
agent/graphs/google_agent.py — orquestra o ciclo do agente para contas Google Ads.

O grafo principal (``agent.graph.compiled_graph``) é multi-plataforma: os nós
analista/estrategista/revisor/executor/memorizador funcionam para qualquer
``platform``. Este módulo apenas seleciona QUAIS contas Google processar e roda
o grafo para cada uma:

  1. Contas ``platform == 'google'`` ativas no Supabase (com cliente ativo); ou
  2. Se não houver nenhuma, e ``GOOGLE_ADS_CUSTOMER_ID`` estiver no ``.env``,
     sintetiza uma conta a partir do ``.env`` (customer_id + refresh_token) para
     que o ciclo rode mesmo sem uma linha em ``ad_accounts``.

Roda por padrão em modo somente-leitura (``GOOGLE_ADS_READ_ONLY=true``): o nó
executor registra a decisão mas ``run_google_action`` não chama a API do Google.
O ``customer_id`` nunca é hardcoded — vem do ``.env`` ou do Supabase.
"""
from __future__ import annotations

from typing import Any

import structlog

from agent.config import settings
from agent.graph import AgentState, compiled_graph
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)


def _initial_state(account: dict, client: dict) -> AgentState:
    return {
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


async def _run_account(account: dict, client: dict) -> None:
    customer_id = account.get("account_id")
    log.info(
        "google_agent.account.start",
        customer_id=customer_id,
        read_only=settings.google_ads_read_only,
    )
    try:
        await compiled_graph.ainvoke(_initial_state(account, client))
        log.info("google_agent.account.done", customer_id=customer_id)
    except Exception:
        log.exception("google_agent.account.error", customer_id=customer_id)


def _fetch_google_accounts() -> list[dict]:
    """Contas Google ativas no Supabase cujo cliente também está ativo."""
    result = (
        supabase.table("ad_accounts")
        .select("*, clients(*)")
        .eq("platform", "google")
        .eq("active", True)
        .execute()
    )
    rows = result.data or []
    return [r for r in rows if (r.get("clients") or {}).get("active", True)]


def _resolve_default_client() -> dict[str, Any]:
    """Contexto de cliente para a conta sintetizada do .env.

    Usa o único cliente ativo, se houver exatamente um; caso contrário, um
    contexto mínimo (sem hardcode de IDs).
    """
    try:
        result = supabase.table("clients").select("*").eq("active", True).execute()
        clients = result.data or []
    except Exception as exc:  # pragma: no cover - rede/DB
        log.warning("google_agent.resolve_client_failed", error=str(exc))
        clients = []

    if len(clients) == 1:
        return clients[0]
    return {"name": "Google Ads (.env)", "vertical": "", "business_dna": {}}


def _synthesize_account() -> dict | None:
    customer_id = (settings.google_ads_customer_id or "").strip()
    if not customer_id:
        return None
    return {
        "id": "",  # sem linha correspondente em ad_accounts; evita "None" no prompt do LLM
        "platform": "google",
        "account_id": customer_id,
        "token": settings.google_ads_refresh_token,
        "client_id": None,
    }


async def run_google_agent(default_client: dict | None = None) -> dict[str, Any]:
    """Roda o ciclo do agente para as contas Google configuradas.

    No-op (com log) se ``GOOGLE_ADS_CUSTOMER_ID`` não estiver no ``.env``.
    Retorna um resumo do ciclo para logging em ``agent.run``.
    """
    customer_id = (settings.google_ads_customer_id or "").strip()
    if not customer_id:
        log.info("google_agent.skip", reason="no_customer_id")
        return {"skipped": True, "reason": "no_customer_id"}

    rows = _fetch_google_accounts()
    if rows:
        log.info(
            "google_agent.start",
            source="supabase",
            accounts=len(rows),
            read_only=settings.google_ads_read_only,
        )
        for row in rows:
            client = row.pop("clients", {}) or {}
            await _run_account(row, client)
        return {
            "skipped": False,
            "source": "supabase",
            "accounts_processed": len(rows),
            "read_only": settings.google_ads_read_only,
        }

    account = _synthesize_account()
    if account is None:  # pragma: no cover - já coberto pelo guard acima
        log.info("google_agent.skip", reason="no_customer_id")
        return {"skipped": True, "reason": "no_customer_id"}

    client = default_client or _resolve_default_client()
    log.info(
        "google_agent.start",
        source="env",
        customer_id=account["account_id"],
        read_only=settings.google_ads_read_only,
    )
    await _run_account(account, client)
    return {
        "skipped": False,
        "source": "env",
        "accounts_processed": 1,
        "customer_id": account["account_id"],
        "read_only": settings.google_ads_read_only,
    }
