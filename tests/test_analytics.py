"""Testes da camada BigQuery Analytics."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.tools import bigquery_client
from api.main import app

CAMPAIGN_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"


@pytest.fixture
def client():
    return TestClient(app)


def test_bigquery_is_configured_false_by_default(mocker):
    mocker.patch.object(bigquery_client.settings, "gcp_project_id", "")
    mocker.patch.object(bigquery_client.settings, "bigquery_dataset", "")
    assert bigquery_client.is_configured() is False


def test_bigquery_is_configured_true(mocker):
    mocker.patch.object(bigquery_client.settings, "gcp_project_id", "veltrus-ads-agent")
    mocker.patch.object(bigquery_client.settings, "bigquery_dataset", "veltrus_analytics")
    assert bigquery_client.is_configured() is True


def test_analytics_attribution_503_when_not_configured(mocker, client):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")
    mocker.patch.object(bigquery_client, "is_configured", return_value=False)

    response = client.get(
        "/analytics/attribution",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 503


def test_analytics_attribution_returns_data(mocker, client):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")
    mocker.patch.object(bigquery_client, "is_configured", return_value=True)
    mocker.patch.object(
        bigquery_client,
        "get_attribution_summary",
        return_value=[
            {
                "campaign_id": CAMPAIGN_UUID,
                "campaign_name": "Camp A",
                "platform": "meta",
                "revenue_closed": 1500.0,
                "roas_real": 3.5,
                "roas_gap": 1.2,
            }
        ],
    )

    response = client.get(
        "/analytics/attribution?platform=meta",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "meta"
    assert body["total"] == 1
    assert body["campaigns"][0]["roas_real"] == 3.5


def test_analytics_performance_returns_metrics(mocker, client):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")
    mocker.patch.object(bigquery_client, "is_configured", return_value=True)
    mocker.patch.object(
        bigquery_client,
        "get_campaign_performance",
        return_value=[
            {
                "date": "2026-06-15",
                "spend": 100.0,
                "roas_platform": 2.1,
                "roas_real": 3.5,
            }
        ],
    )

    response = client.get(
        f"/analytics/campaigns/{CAMPAIGN_UUID}/performance",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["campaign_id"] == CAMPAIGN_UUID
    assert len(body["metrics"]) == 1


def test_analytics_sync_triggers_run_sync(mocker, client):
    from agent.config import settings
    from agent.tools import bigquery_sync

    mocker.patch.object(settings, "api_secret_key", "test-key")
    mocker.patch.object(bigquery_client, "is_configured", return_value=True)
    sync_mock = mocker.patch.object(
        bigquery_sync,
        "run_sync",
        return_value={"campaigns": 5, "deals": 2},
    )

    response = client.post(
        "/analytics/sync",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    sync_mock.assert_called_once()


def test_table_ref_uses_project_and_dataset(mocker):
    mocker.patch.object(bigquery_client.settings, "gcp_project_id", "veltrus-ads-agent")
    mocker.patch.object(bigquery_client.settings, "bigquery_dataset", "veltrus_analytics")
    ref = bigquery_client.table_ref("campaign_attribution")
    assert ref == "`veltrus-ads-agent.veltrus_analytics.campaign_attribution`"
