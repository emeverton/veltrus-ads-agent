"""
scripts/kill_switch.py — Kill switch de segurança financeira

Roda a cada hora via cron. Completamente independente do agente LangGraph.
Verifica 3 regras por campanha e pausa/alerta conforme necessário.

Regras:
  1. spend_overage  — gasto hoje > daily_budget × 1.1  → pausa + log
  2. cpa_spike      — cpa_click hoje > cpa_max × 2.0   → pausa + log
  3. roas_critical  — roas_click hoje < 0.5            → alerta + log (sem pausa)

Uso:
  python scripts/kill_switch.py           # modo real
  python scripts/kill_switch.py --dry-run # simula sem chamar APIs externas
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import date, timezone
from typing import Any

import structlog

from agent.config import settings
from agent.tools import meta_ads, google_ads
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Limites configuráveis
# ---------------------------------------------------------------------------
SPEND_MULT: float = 1.1   # gasto > budget × 1.1 dispara
CPA_MULT:   float = 2.0   # cpa > cpa_max × 2.0 dispara
ROAS_MIN:   float = 0.5   # roas < 0.5 dispara alerta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_cpa_max(business_dna: dict[str, Any] | None) -> float | None:
    """Extrai cpa_max do campo objetivo_principal do business_dna.

    Aceita formatos como 'CPA < $25', 'CPA abaixo de $30', 'custo por resultado < 20'.
    """
    if not business_dna:
        return None
    objetivo = business_dna.get("objetivo_principal", "") or ""
    match = re.search(r"cpa\s*[<abaixode\s]*\$?\s*(\d+(?:\.\d+)?)", objetivo, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _today() -> str:
    return date.today().isoformat()


async def _get_account_token(account_id: str) -> str:
    """Busca o access_token da conta no Supabase."""
    resp = (
        supabase.table("ad_accounts")
        .select("token")
        .eq("id", account_id)
        .single()
        .execute()
    )
    return (resp.data or {}).get("token") or ""


def _log_to_db(
    *,
    account_external_id: str,
    campaign_external_id: str,
    campaign_name: str,
    platform: str,
    client_name: str | None,
    trigger_type: str,
    action_taken: str,
    trigger_value: float,
    threshold_value: float,
    dry_run: bool,
) -> None:
    """Insere uma linha em kill_switch_log."""
    if dry_run:
        action_taken = "dry_run"

    try:
        supabase.table("kill_switch_log").insert({
            "account_external_id":  account_external_id,
            "campaign_external_id": campaign_external_id,
            "campaign_name":        campaign_name,
            "platform":             platform,
            "client_name":          client_name,
            "trigger_type":         trigger_type,
            "action_taken":         action_taken,
            "trigger_value":        round(trigger_value, 4),
            "threshold_value":      round(threshold_value, 4),
        }).execute()
    except Exception as exc:  # never let DB failures stop the safety check
        log.error("kill_switch.db_log_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Ações de pausa por plataforma
# ---------------------------------------------------------------------------
async def _pause_meta(campaign_external_id: str, token: str, dry_run: bool) -> str:
    if dry_run:
        log.info("kill_switch.dry_run.meta_pause", campaign_id=campaign_external_id)
        return "dry_run"
    try:
        await meta_ads.pause_campaign(campaign_external_id, token)
        return "paused"
    except Exception as exc:
        log.error("kill_switch.meta_pause_failed", campaign_id=campaign_external_id, error=str(exc))
        return "pause_failed"


async def _pause_google(campaign_external_id: str, credentials: dict, dry_run: bool) -> str:
    if dry_run:
        log.info("kill_switch.dry_run.google_pause", campaign_id=campaign_external_id)
        return "dry_run"
    try:
        await google_ads.pause_campaign(campaign_external_id, credentials)
        return "paused"
    except Exception as exc:
        log.error("kill_switch.google_pause_failed", campaign_id=campaign_external_id, error=str(exc))
        return "pause_failed"


# ---------------------------------------------------------------------------
# Verificação por campanha
# ---------------------------------------------------------------------------
async def check_campaign(
    *,
    campaign: dict[str, Any],
    account: dict[str, Any],
    client: dict[str, Any] | None,
    token: str,
    dry_run: bool,
) -> int:
    """Executa as 3 verificações de segurança para uma campanha.

    Retorna o número de regras disparadas.
    """
    today = _today()
    camp_id      = campaign["id"]
    camp_ext_id  = campaign["campaign_id"]
    camp_name    = campaign.get("name", camp_ext_id)
    platform     = campaign.get("platform", account.get("platform", "meta"))
    account_ext  = account.get("account_id", "")
    client_name  = (client or {}).get("name")
    daily_budget = float(campaign.get("daily_budget", 0) or 0)

    # Busca métricas de hoje no Supabase (usa dados do normalizer se disponível)
    metrics_resp = (
        supabase.table("daily_metrics")
        .select("spend, cpa, roas, conversions, confidence_score, cpa_click:cpa, roas_click:roas")
        .eq("campaign_id", camp_id)
        .eq("date", today)
        .maybe_single()
        .execute()
    )
    metrics = metrics_resp.data or {}

    spend_today = float(metrics.get("spend", 0) or 0)
    # Prefere cpa/roas já calculados; o normalizer pode ter sobrescrito via confidence_score
    cpa_today   = float(metrics.get("cpa", 0) or 0) or None
    roas_today  = float(metrics.get("roas", 0) or 0) or None

    # Se não há dados de hoje, nada a verificar
    if not metrics:
        log.debug(
            "kill_switch.no_data_today",
            campaign=camp_name,
            date=today,
        )
        return 0

    triggered = 0
    business_dna = (client or {}).get("business_dna") or {}
    cpa_max = _extract_cpa_max(business_dna)

    # ------------------------------------------------------------------
    # Regra 1 — spend_overage
    # ------------------------------------------------------------------
    if daily_budget > 0 and spend_today > daily_budget * SPEND_MULT:
        threshold = daily_budget * SPEND_MULT
        log.critical(
            "kill_switch.spend_overage",
            campaign=camp_name,
            platform=platform,
            spend_today=spend_today,
            daily_budget=daily_budget,
            threshold=threshold,
            dry_run=dry_run,
        )

        if platform == "meta":
            action = await _pause_meta(camp_ext_id, token, dry_run)
        else:
            google_creds = {
                "client_id":     settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": token,
            }
            action = await _pause_google(camp_ext_id, google_creds, dry_run)

        _log_to_db(
            account_external_id=account_ext,
            campaign_external_id=camp_ext_id,
            campaign_name=camp_name,
            platform=platform,
            client_name=client_name,
            trigger_type="spend_overage",
            action_taken=action,
            trigger_value=spend_today,
            threshold_value=threshold,
            dry_run=dry_run,
        )
        triggered += 1

    # ------------------------------------------------------------------
    # Regra 2 — cpa_spike
    # ------------------------------------------------------------------
    if cpa_max and cpa_today and cpa_today > cpa_max * CPA_MULT:
        threshold = cpa_max * CPA_MULT
        log.critical(
            "kill_switch.cpa_spike",
            campaign=camp_name,
            platform=platform,
            cpa_today=cpa_today,
            cpa_max=cpa_max,
            threshold=threshold,
            dry_run=dry_run,
        )

        if platform == "meta":
            action = await _pause_meta(camp_ext_id, token, dry_run)
        else:
            google_creds = {
                "client_id":     settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": token,
            }
            action = await _pause_google(camp_ext_id, google_creds, dry_run)

        _log_to_db(
            account_external_id=account_ext,
            campaign_external_id=camp_ext_id,
            campaign_name=camp_name,
            platform=platform,
            client_name=client_name,
            trigger_type="cpa_spike",
            action_taken=action,
            trigger_value=cpa_today,
            threshold_value=threshold,
            dry_run=dry_run,
        )
        triggered += 1

    # ------------------------------------------------------------------
    # Regra 3 — roas_critical (apenas alerta, não pausa)
    # ------------------------------------------------------------------
    if roas_today is not None and roas_today < ROAS_MIN:
        log.critical(
            "kill_switch.roas_critical",
            campaign=camp_name,
            platform=platform,
            roas_today=roas_today,
            roas_min=ROAS_MIN,
            dry_run=dry_run,
        )
        _log_to_db(
            account_external_id=account_ext,
            campaign_external_id=camp_ext_id,
            campaign_name=camp_name,
            platform=platform,
            client_name=client_name,
            trigger_type="roas_critical",
            action_taken="dry_run" if dry_run else "alerted",
            trigger_value=roas_today,
            threshold_value=ROAS_MIN,
            dry_run=False,  # já ajustado acima
        )
        triggered += 1

    return triggered


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------
async def main(dry_run: bool = False) -> int:
    log.info("kill_switch.start", dry_run=dry_run, date=_today())

    # Busca todas as contas ativas com cliente e campanhas ativas
    accounts_resp = (
        supabase.table("ad_accounts")
        .select("*, clients(*), campaigns(id, campaign_id, name, platform, status, daily_budget)")
        .eq("campaigns.status", "active")
        .execute()
    )
    accounts = accounts_resp.data or []

    if not accounts:
        log.info("kill_switch.no_accounts")
        return 0

    total_triggered = 0

    for account in accounts:
        client     = account.pop("clients", None)
        campaigns  = account.pop("campaigns", None) or []
        platform   = account.get("platform", "meta")
        account_id = account.get("id", "")
        token      = account.get("token", "")

        if not token:
            log.warning("kill_switch.missing_token", account_id=account_id)
            continue

        for campaign in campaigns:
            if campaign.get("status") != "active":
                continue
            try:
                n = await check_campaign(
                    campaign=campaign,
                    account=account,
                    client=client,
                    token=token,
                    dry_run=dry_run,
                )
                total_triggered += n
            except Exception as exc:
                log.error(
                    "kill_switch.campaign_check_failed",
                    campaign_id=campaign.get("campaign_id"),
                    error=str(exc),
                )

    log.info(
        "kill_switch.done",
        total_accounts=len(accounts),
        total_triggered=total_triggered,
        dry_run=dry_run,
    )
    return total_triggered


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Veltrus Kill Switch — proteção financeira")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula verificações sem pausar campanhas nem chamar APIs externas",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
