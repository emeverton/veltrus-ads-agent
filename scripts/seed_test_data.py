"""
Insere dados de teste no Supabase para desenvolvimento local.
Idempotente: verifica se os registros já existem antes de inserir.

Uso:
    python -m scripts.seed_test_data
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, __file__.replace("/scripts/seed_test_data.py", ""))

from agent.tools.supabase_client import supabase

# ---------------------------------------------------------------------------
# Constantes de seed
# ---------------------------------------------------------------------------
CLIENT_NAME = "Veltrus Test"
META_ACCOUNT_ID = "act_1616000166323786"
CAMPAIGN_EXTERNAL_ID = "23858001234560"
CAMPAIGN_NAME = "Veltrus Test | Conversões | Lookalike 2%"
SEED_DAYS = 7

# Simula performance realista: trending levemente pior nos últimos 2 dias
# (para o ANALISTA ter anomalias para detectar)
_DAILY_DATA = [
    # date_offset, spend,  impressions, clicks, conversions, roas_multiplier
    (-6, 120.50,  18_400, 552,  8.2,  1.0),
    (-5, 134.20,  19_100, 592,  9.1,  1.05),
    (-4, 118.80,  17_900, 519,  7.8,  0.98),
    (-3, 145.60,  20_800, 645,  10.3, 1.10),
    (-2, 198.40,  22_100, 619,  7.1,  0.85),  # spend alto, conversions caindo
    (-1, 201.30,  21_800, 545,  5.9,  0.72),  # piora — CPA spike + ROAS negativo
    ( 0, 187.90,  20_500, 493,  4.8,  0.61),  # hoje — anomalia clara
]


def _round2(v: float) -> float:
    return round(v, 2)


def _round4(v: float) -> float:
    return round(v, 4)


def _build_metrics(spend: float, impressions: int, clicks: int, conversions: float, roas_mult: float) -> dict:
    revenue = spend * 1.8 * roas_mult          # receita simulada
    cpa = spend / conversions if conversions > 0 else None
    roas = revenue / spend if spend > 0 else None
    ctr = clicks / impressions if impressions > 0 else 0.0
    return {
        "spend": _round4(spend),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": _round4(conversions),
        "cpa": _round4(cpa) if cpa else None,
        "roas": _round4(roas) if roas else None,
        "ctr": _round4(ctr),
        "raw_payload": {
            "source": "seed_test_data",
            "revenue_simulated": _round2(revenue),
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _upsert_client() -> dict:
    existing = (
        supabase.table("clients")
        .select("id, name")
        .eq("name", CLIENT_NAME)
        .limit(1)
        .execute()
    )
    if existing.data:
        print(f"  [skip] cliente já existe: {existing.data[0]['id']}")
        return existing.data[0]

    row = {
        "name": CLIENT_NAME,
        "vertical": "ecommerce",
        "active": True,
        "business_dna": {
            "descricao": "Loja de moda feminina premium com forte presença digital.",
            "tom_de_voz": "sofisticado, próximo, aspiracional",
            "produtos_destaque": ["vestidos", "acessórios", "calçados"],
            "ticket_medio_brl": 380,
            "sazonalidade": ["dia das mães", "black friday", "natal"],
            "restricoes": [
                "não pausar campanhas sem aprovação humana em feriados",
                "budget mínimo diário: $50",
            ],
            "objetivo_principal": "maximizar ROAS mantendo CPA < $25",
        },
    }
    result = supabase.table("clients").insert(row).execute()
    client = result.data[0]
    print(f"  [ok] cliente criado: {client['id']}")
    return client


def _upsert_ad_account(client_id: str) -> dict:
    existing = (
        supabase.table("ad_accounts")
        .select("id, account_id")
        .eq("platform", "meta")
        .eq("account_id", META_ACCOUNT_ID)
        .limit(1)
        .execute()
    )
    if existing.data:
        print(f"  [skip] conta Meta já existe: {existing.data[0]['id']}")
        return existing.data[0]

    row = {
        "client_id": client_id,
        "platform": "meta",
        "account_id": META_ACCOUNT_ID,
        "token": "SEED_TOKEN_PLACEHOLDER",
        "active": True,
    }
    result = supabase.table("ad_accounts").insert(row).execute()
    account = result.data[0]
    print(f"  [ok] conta Meta criada: {account['id']}")
    return account


def _upsert_campaign(ad_account_uuid: str) -> dict:
    existing = (
        supabase.table("campaigns")
        .select("id, name")
        .eq("account_id", ad_account_uuid)
        .eq("campaign_id", CAMPAIGN_EXTERNAL_ID)
        .limit(1)
        .execute()
    )
    if existing.data:
        print(f"  [skip] campanha já existe: {existing.data[0]['id']}")
        return existing.data[0]

    row = {
        "account_id": ad_account_uuid,
        "campaign_id": CAMPAIGN_EXTERNAL_ID,
        "name": CAMPAIGN_NAME,
        "platform": "meta",
        "status": "active",
        "objective": "CONVERSIONS",
        "daily_budget": 200.00,
    }
    result = supabase.table("campaigns").insert(row).execute()
    campaign = result.data[0]
    print(f"  [ok] campanha criada: {campaign['id']}")
    return campaign


def _upsert_daily_metrics(campaign_uuid: str) -> int:
    today = date.today()
    inserted = 0

    for offset, spend, impressions, clicks, conversions, roas_mult in _DAILY_DATA:
        metric_date = (today + timedelta(days=offset)).isoformat()

        # Verifica se já existe para este dia
        existing = (
            supabase.table("daily_metrics")
            .select("id")
            .eq("campaign_id", campaign_uuid)
            .eq("date", metric_date)
            .limit(1)
            .execute()
        )
        if existing.data:
            print(f"  [skip] métricas {metric_date} já existem")
            continue

        metrics = _build_metrics(spend, impressions, clicks, conversions, roas_mult)
        row = {"campaign_id": campaign_uuid, "date": metric_date, **metrics}
        supabase.table("daily_metrics").insert(row).execute()
        print(
            f"  [ok] {metric_date} | spend=${metrics['spend']:.2f} "
            f"cpa={metrics['cpa']} roas={metrics['roas']} ctr={metrics['ctr']}"
        )
        inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("\n▶ Inserindo cliente...")
    client = _upsert_client()

    print("\n▶ Inserindo conta de anúncios (Meta)...")
    account = _upsert_ad_account(client["id"])

    print("\n▶ Inserindo campanha...")
    campaign = _upsert_campaign(account["id"])

    print(f"\n▶ Inserindo {SEED_DAYS} dias de métricas...")
    n = _upsert_daily_metrics(campaign["id"])

    print(f"\n✓ Seed concluído — {n} linhas de métricas inseridas.")
    print(f"  client_id:   {client['id']}")
    print(f"  account_id:  {account['id']}")
    print(f"  campaign_id: {campaign['id']}\n")


if __name__ == "__main__":
    main()
