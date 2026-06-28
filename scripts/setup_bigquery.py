"""Setup BigQuery dataset, tables and attribution view for Veltrus Revenue OS."""
from __future__ import annotations

from google.cloud import bigquery

PROJECT_ID = "veltrus-ads-agent"
DATASET_ID = "veltrus_attribution"


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID)

    dataset = bigquery.Dataset(f"{PROJECT_ID}.{DATASET_ID}")
    dataset.location = "southamerica-east1"
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
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        table = bigquery.Table(table_ref, schema=schema)
        client.create_table(table, exists_ok=True)
        print(f"Tabela criada: {table_name}")

    view_sql = f"""
    CREATE OR REPLACE VIEW `{PROJECT_ID}.{DATASET_ID}.campaign_real_roas` AS
    SELECT
      cs.campaign_id,
      cs.external_campaign_id,
      cs.platform,
      SUM(cs.spend) AS total_spend,
      COALESCE(SUM(d.revenue_amount), 0) AS revenue_real,
      COUNT(DISTINCT l.id) AS leads_total,
      COUNT(DISTINCT d.id) AS deals_closed,
      SAFE_DIVIDE(COALESCE(SUM(d.revenue_amount), 0), NULLIF(SUM(cs.spend), 0)) AS roas_real,
      MAX(cs.platform_roas) AS roas_plataforma,
      MAX(cs.synced_at) AS last_sync
    FROM `{PROJECT_ID}.{DATASET_ID}.campaign_spend` cs
    LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.leads` l
      ON l.campaign_id = cs.campaign_id
    LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.deals` d
      ON d.campaign_id = cs.campaign_id
    GROUP BY cs.campaign_id, cs.external_campaign_id, cs.platform
    """
    client.query(view_sql).result()
    print("View campaign_real_roas criada")


if __name__ == "__main__":
    main()
