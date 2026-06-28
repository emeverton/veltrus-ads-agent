"""
BigQuery setup — Veltrus Revenue OS
Cria dataset, tabelas e view de attribution no projeto veltrus-ads-agent.

Uso:
  python scripts/setup_bigquery.py

Pré-requisito:
  GOOGLE_CLOUD_PROJECT=veltrus-ads-agent no ambiente, ou ADC configurado.
  google-cloud-bigquery instalado (ver requirements.txt).
"""
from __future__ import annotations

import os
import sys

from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "veltrus-ads-agent")
DATASET = os.environ.get("BIGQUERY_DATASET", "veltrus_attribution")
LOCATION = os.environ.get("BIGQUERY_LOCATION", "southamerica-east1")

client = bigquery.Client(project=PROJECT)


def create_dataset() -> None:
    dataset_ref = f"{PROJECT}.{DATASET}"
    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = LOCATION
    dataset.description = "Attribution analytics — Veltrus Revenue OS"
    client.create_dataset(dataset, exists_ok=True)
    print(f"[OK] Dataset: {dataset_ref}")


TABLES = {
    "leads": [
        bigquery.SchemaField("id",                   "STRING",    description="UUID do lead (Supabase)"),
        bigquery.SchemaField("client_id",            "STRING",    description="UUID do cliente"),
        bigquery.SchemaField("campaign_id",          "STRING",    description="UUID interno da campanha"),
        bigquery.SchemaField("external_campaign_id", "STRING",    description="ID externo (Meta/Google)"),
        bigquery.SchemaField("phone",                "STRING",    description="Telefone do lead"),
        bigquery.SchemaField("crm_deal_id",          "STRING",    description="ID do deal no Kommo"),
        bigquery.SchemaField("lead_source",          "STRING",    description="Fonte: meta | google"),
        bigquery.SchemaField("created_at",           "TIMESTAMP", description="Data de criação do lead"),
    ],
    "deals": [
        bigquery.SchemaField("id",             "STRING",    description="UUID do deal (Supabase)"),
        bigquery.SchemaField("lead_id",        "STRING",    description="UUID do lead relacionado"),
        bigquery.SchemaField("campaign_id",    "STRING",    description="UUID interno da campanha"),
        bigquery.SchemaField("client_id",      "STRING",    description="UUID do cliente"),
        bigquery.SchemaField("crm_deal_id",    "STRING",    description="ID do deal no Kommo"),
        bigquery.SchemaField("revenue_amount", "FLOAT64",   description="Receita do deal em BRL"),
        bigquery.SchemaField("currency",       "STRING",    description="Moeda (BRL)"),
        bigquery.SchemaField("closed_at",      "TIMESTAMP", description="Data de fechamento"),
    ],
    "campaign_spend": [
        bigquery.SchemaField("campaign_id",          "STRING",  description="UUID interno da campanha"),
        bigquery.SchemaField("external_campaign_id", "STRING",  description="ID externo (Meta/Google)"),
        bigquery.SchemaField("platform",             "STRING",  description="meta | google"),
        bigquery.SchemaField("date",                 "DATE",    description="Data do spend"),
        bigquery.SchemaField("spend",                "FLOAT64", description="Gasto em USD"),
        bigquery.SchemaField("impressions",          "INTEGER", description="Impressões"),
        bigquery.SchemaField("clicks",               "INTEGER", description="Cliques"),
        bigquery.SchemaField("platform_conversions", "FLOAT64", description="Conversões reportadas pela plataforma"),
        bigquery.SchemaField("platform_roas",        "FLOAT64", description="ROAS reportado pela plataforma"),
        bigquery.SchemaField("synced_at",            "TIMESTAMP", description="Timestamp da sincronização"),
    ],
}


def create_tables() -> None:
    for table_name, schema in TABLES.items():
        table_ref = f"{PROJECT}.{DATASET}.{table_name}"
        table = bigquery.Table(table_ref, schema=schema)
        client.create_table(table, exists_ok=True)
        print(f"[OK] Tabela: {table_name}")


VIEW_SQL = f"""
CREATE OR REPLACE VIEW `{PROJECT}.{DATASET}.campaign_real_roas` AS
SELECT
  cs.campaign_id,
  cs.external_campaign_id,
  cs.platform,
  SUM(cs.spend)                                           AS total_spend,
  COALESCE(SUM(d.revenue_amount), 0)                      AS revenue_real,
  COUNT(DISTINCT l.id)                                    AS leads_total,
  COUNT(DISTINCT d.id)                                    AS deals_closed,
  SAFE_DIVIDE(
    COALESCE(SUM(d.revenue_amount), 0),
    NULLIF(SUM(cs.spend), 0)
  )                                                        AS roas_real,
  MAX(cs.platform_roas)                                   AS roas_plataforma,
  MAX(cs.synced_at)                                       AS last_sync
FROM `{PROJECT}.{DATASET}.campaign_spend` cs
LEFT JOIN `{PROJECT}.{DATASET}.leads` l
  ON l.campaign_id = cs.campaign_id
LEFT JOIN `{PROJECT}.{DATASET}.deals` d
  ON d.campaign_id = cs.campaign_id
GROUP BY cs.campaign_id, cs.external_campaign_id, cs.platform
"""


def create_view() -> None:
    client.query(VIEW_SQL).result()
    print(f"[OK] View: campaign_real_roas")


if __name__ == "__main__":
    print(f"Configurando BigQuery: projeto={PROJECT}, dataset={DATASET}, location={LOCATION}")
    try:
        create_dataset()
        create_tables()
        create_view()
        print("\nSetup concluído com sucesso.")
    except Exception as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)
