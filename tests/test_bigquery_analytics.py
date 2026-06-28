"""Testes da camada analytics + BigQuery sem GCP real."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent.tools import bigquery_analytics
from api.main import app


CAMPAIGN_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"


def test_normalize_campaign_daily_row_builds_key_and_types():
    row = {
        "campaign_uuid": CAMPAIGN_UUID,
        "date": "2026-06-16",
        "spend_usd": "100.50",
        "impressions": "1000",
        "clicks": "50",
        "conversions": "5",
        "roas_platform": "2.25",
        "revenue_closed": "500",
        "leads_total": "4",
        "deals_closed": "2",
        "roas_real": "4.975",
    }

    out = bigquery_analytics.normalize_campaign_daily_row(row)

    assert out["analytics_key"] == f"{CAMPAIGN_UUID}:2026-06-16"
    assert out["spend_usd"] == 100.50
    assert out["impressions"] == 1000
    assert out["roas_real"] == 4.975
    assert out["synced_at"]


def test_fetch_campaign_daily_rows_reads_supabase_view(mocker):
    fake_supabase = mocker.patch.object(bigquery_analytics, "supabase")
    execute = (
        fake_supabase.table.return_value.select.return_value.order.return_value.limit.return_value
        .eq.return_value.gte.return_value.execute
    )
    execute.return_value.data = [
        {"campaign_uuid": CAMPAIGN_UUID, "date": "2026-06-16", "spend_usd": 10}
    ]

    rows = bigquery_analytics.fetch_campaign_daily_rows(
        campaign_uuid=CAMPAIGN_UUID,
        since="2026-06-01",
        limit=100,
    )

    fake_supabase.table.assert_called_once_with("analytics_campaign_daily")
    assert rows[0]["analytics_key"] == f"{CAMPAIGN_UUID}:2026-06-16"


def test_sync_disabled_returns_skipped(mocker):
    mocker.patch.object(bigquery_analytics.settings, "bigquery_enabled", False)

    result = bigquery_analytics.sync_campaign_daily_to_bigquery(
        rows=[{"campaign_uuid": CAMPAIGN_UUID, "date": "2026-06-16"}]
    )

    assert result["enabled"] is False
    assert result["skipped"] is True
    assert result["row_count"] == 1


def test_sync_enabled_uses_staging_merge(mocker):
    class _FakeJob:
        errors = None

        def result(self):
            return None

    class _FakeWriteDisposition:
        WRITE_TRUNCATE = "WRITE_TRUNCATE"

    class _FakeBigQuery:
        WriteDisposition = _FakeWriteDisposition

        class SchemaField:
            def __init__(self, name, field_type, mode="NULLABLE"):
                self.name = name
                self.field_type = field_type
                self.mode = mode

        class Table:
            def __init__(self, table_id, schema=None):
                self.table_id = table_id
                self.schema = schema

        class LoadJobConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    class _FakeClient:
        def __init__(self):
            self.loaded_rows = None
            self.merge_sql = ""
            self.deleted_table = ""

        def create_table(self, table):
            return table

        def load_table_from_json(self, rows, table_id, job_config=None):
            self.loaded_rows = rows
            return _FakeJob()

        def query(self, sql):
            self.merge_sql = sql
            return _FakeJob()

        def delete_table(self, table_id, not_found_ok=False):
            self.deleted_table = table_id

    fake_client = _FakeClient()
    mocker.patch.object(bigquery_analytics.settings, "bigquery_enabled", True)
    mocker.patch.object(bigquery_analytics, "bigquery", _FakeBigQuery)
    mocker.patch.object(bigquery_analytics, "_ensure_dataset_and_table", return_value=None)

    result = bigquery_analytics.sync_campaign_daily_to_bigquery(
        rows=[{"campaign_uuid": CAMPAIGN_UUID, "date": "2026-06-16", "spend_usd": 10}],
        client=fake_client,
    )

    assert result["enabled"] is True
    assert result["skipped"] is False
    assert result["row_count"] == 1
    assert fake_client.loaded_rows[0]["analytics_key"] == f"{CAMPAIGN_UUID}:2026-06-16"
    assert "MERGE `veltrus-ads-agent.veltrus_analytics.campaign_daily_performance`" in fake_client.merge_sql
    assert fake_client.deleted_table


def test_analytics_bigquery_sync_dry_run_endpoint(mocker):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")
    mocker.patch("api.routers.analytics.fetch_campaign_daily_rows", return_value=[{"x": 1}])
    sync_mock = mocker.patch("api.routers.analytics.sync_campaign_daily_to_bigquery")
    client = TestClient(app)

    response = client.post(
        "/analytics/bigquery/sync",
        headers={"X-API-Key": "test-key"},
        json={"since": "2026-06-01", "dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert response.json()["row_count"] == 1
    sync_mock.assert_not_called()
