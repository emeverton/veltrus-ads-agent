"""Cria dataset, tabelas e view analítica de attribution no BigQuery."""
from __future__ import annotations

import os

from google.cloud import bigquery


PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "veltrus-ads-agent")
DATASET_ID = os.getenv("BIGQUERY_DATASET", "veltrus_attribution")
LOCATION = os.getenv("BIGQUERY_LOCATION", "southamerica-east1")


def _table_ref(table_name: str) -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.{table_name}"


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID)

    dataset = bigquery.Dataset(f"{PROJECT_ID}.{DATASET_ID}")
    dataset.location = LOCATION
    dataset.description = "Attribution analytics — Veltrus Revenue OS"
    client.create_dataset(dataset, exists_ok=True)
    print(f"Dataset criado: {DATASET_ID}")

    tables = {
        "leads": [
            bigquery.SchemaField("id", "STRING"),
            bigquery.SchemaField("client_id", "STRING"),
            bigquery.SchemaField("campaign_id", "STRING"),
            bigquery.SchemaField("external_campaign_id", "STRING"),
            bigquery.SchemaField("phone", "STRING"),
            bigquery.SchemaField("crm_deal_id", "STRING"),
            bigquery.SchemaField("lead_source", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP"),
        ],
        "deals": [
            bigquery.SchemaField("id", "STRING"),
            bigquery.SchemaField("lead_id", "STRING"),
            bigquery.SchemaField("campaign_id", "STRING"),
            bigquery.SchemaField("client_id", "STRING"),
            bigquery.SchemaField("crm_deal_id", "STRING"),
            bigquery.SchemaField("revenue_amount", "FLOAT64"),
            bigquery.SchemaField("currency", "STRING"),
            bigquery.SchemaField("closed_at", "TIMESTAMP"),
        ],
        "campaign_spend": [
            bigquery.SchemaField("campaign_id", "STRING"),
            bigquery.SchemaField("external_campaign_id", "STRING"),
            bigquery.SchemaField("platform", "STRING"),
            bigquery.SchemaField("date", "DATE"),
            bigquery.SchemaField("spend", "FLOAT64"),
            bigquery.SchemaField("impressions", "INTEGER"),
            bigquery.SchemaField("clicks", "INTEGER"),
            bigquery.SchemaField("platform_conversions", "FLOAT64"),
            bigquery.SchemaField("platform_roas", "FLOAT64"),
            bigquery.SchemaField("synced_at", "TIMESTAMP"),
        ],
    }

    for table_name, schema in tables.items():
        table = bigquery.Table(_table_ref(table_name), schema=schema)
        client.create_table(table, exists_ok=True)
        print(f"Tabela criada: {table_name}")

    view_sql = f"""
    CREATE OR REPLACE VIEW `{PROJECT_ID}.{DATASET_ID}.campaign_real_roas` AS
    WITH spend AS (
      SELECT
        campaign_id,
        external_campaign_id,
        platform,
        SUM(spend) AS total_spend,
        MAX(platform_roas) AS roas_plataforma,
        MAX(synced_at) AS last_sync
      FROM `{PROJECT_ID}.{DATASET_ID}.campaign_spend`
      GROUP BY campaign_id, external_campaign_id, platform
    ),
    leads AS (
      SELECT
        campaign_id,
        COUNT(DISTINCT id) AS leads_total
      FROM `{PROJECT_ID}.{DATASET_ID}.leads`
      GROUP BY campaign_id
    ),
    deals AS (
      SELECT
        campaign_id,
        SUM(revenue_amount) AS revenue_real,
        COUNT(DISTINCT id) AS deals_closed
      FROM `{PROJECT_ID}.{DATASET_ID}.deals`
      GROUP BY campaign_id
    )
    SELECT
      spend.campaign_id,
      spend.external_campaign_id,
      spend.platform,
      spend.total_spend,
      COALESCE(deals.revenue_real, 0) AS revenue_real,
      COALESCE(leads.leads_total, 0) AS leads_total,
      COALESCE(deals.deals_closed, 0) AS deals_closed,
      SAFE_DIVIDE(COALESCE(deals.revenue_real, 0), NULLIF(spend.total_spend, 0)) AS roas_real,
      spend.roas_plataforma,
      spend.last_sync
    FROM spend
    LEFT JOIN leads ON leads.campaign_id = spend.campaign_id
    LEFT JOIN deals ON deals.campaign_id = spend.campaign_id
    """
    client.query(view_sql).result()
    print("View campaign_real_roas criada")


if __name__ == "__main__":
    main()
