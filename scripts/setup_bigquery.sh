#!/usr/bin/env bash
# =============================================================================
# Setup BigQuery Analytics Layer — GCP project: veltrus-ads-agent
# =============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-veltrus-ads-agent}"
DATASET="${BIGQUERY_DATASET:-veltrus_analytics}"
LOCATION="${BIGQUERY_LOCATION:-US}"
SCHEMA_FILE="$(dirname "$0")/../analytics/bigquery/schema.sql"

echo "→ Projeto GCP: $PROJECT_ID"
echo "→ Dataset: $DATASET ($LOCATION)"

gcloud config set project "$PROJECT_ID"

echo "→ Criando dataset (se não existir)..."
bq --location="$LOCATION" mk --dataset --description "Veltrus Ads Agent analytics" "$PROJECT_ID:$DATASET" 2>/dev/null || true

echo "→ Aplicando schema..."
# Substitui placeholder do dataset no schema
sed "s/veltrus_analytics/$DATASET/g" "$SCHEMA_FILE" | bq query --use_legacy_sql=false

echo "→ Criando service account (se não existir)..."
SA_NAME="veltrus-bq-sync"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="Veltrus BigQuery Sync" 2>/dev/null || true

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataEditor" --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" --quiet

echo ""
echo "✓ BigQuery pronto."
echo "  Dataset: ${PROJECT_ID}:${DATASET}"
echo "  SA: ${SA_EMAIL}"
echo ""
echo "Próximos passos:"
echo "  1. Baixe a chave: gcloud iam service-accounts keys create bq-sa.json --iam-account=${SA_EMAIL}"
echo "  2. Configure .env: GCP_PROJECT_ID, BIGQUERY_DATASET, GOOGLE_APPLICATION_CREDENTIALS=bq-sa.json"
echo "  3. Rode sync: python scripts/sync_to_bigquery.py"
