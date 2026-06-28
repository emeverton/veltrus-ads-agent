"""
Testes do attribution loop — leads, deals, ROAS real.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agent.graph as graph
from agent.tools import campaign_registry
from api.main import app

CAMPAIGN_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"
EXTERNAL_ID = "120249189080650247"


@pytest.fixture
def client():
    return TestClient(app)


def test_get_campaign_real_roas_valid_uuid(mocker):
    mocker.patch(
        "agent.tools.bigquery_attribution.get_campaign_real_roas",
        return_value={
            "revenue_real": 1500.0,
            "leads_total": 3,
            "deals_closed": 1,
        },
    )

    result = campaign_registry.get_campaign_real_roas(CAMPAIGN_UUID)

    assert result["revenue_closed"] == 1500.0
    assert result["leads_total"] == 3
    assert result["deals_closed"] == 1


@pytest.mark.parametrize("bad_uuid", ["n/a", "", None, "not-a-uuid", EXTERNAL_ID])
def test_get_campaign_real_roas_invalid_returns_zeros(mocker, bad_uuid):
    mocker.patch(
        "agent.tools.bigquery_attribution.get_campaign_real_roas",
        return_value={"revenue_real": 0, "leads_total": 0, "deals_closed": 0},
    )

    result = campaign_registry.get_campaign_real_roas(bad_uuid)

    assert result == {"revenue_closed": 0, "leads_total": 0, "deals_closed": 0}


def test_get_campaign_real_roas_failure_returns_zeros(mocker):
    mocker.patch(
        "agent.tools.bigquery_attribution.get_campaign_real_roas",
        return_value={"revenue_real": 0.0, "leads_total": 0, "deals_closed": 0},
    )

    result = campaign_registry.get_campaign_real_roas(CAMPAIGN_UUID)

    assert result == {"revenue_closed": 0, "leads_total": 0, "deals_closed": 0}


@pytest.mark.asyncio
async def test_analista_enriches_campaigns_with_roas_real(mocker):
    campaign_registry.set_campaign_id_map({EXTERNAL_ID: CAMPAIGN_UUID})
    mocker.patch.object(
        graph,
        "_sync_campaign_registry",
        return_value={EXTERNAL_ID: CAMPAIGN_UUID},
    )
    mocker.patch.object(
        graph,
        "_agent_loop",
        return_value='{"campaigns_analyzed":[{"campaign_id":"'
        + EXTERNAL_ID
        + '","name":"Camp A","platform":"meta","last_spend_usd":100}],"anomalies":[]}',
    )
    mocker.patch.object(
        graph,
        "get_campaign_real_roas",
        return_value={
            "roas_real": 5.0,
            "revenue_real": 500.0,
            "leads_total": 2,
            "deals_closed": 1,
        },
    )

    state = {
        "account": {
            "id": "922f2273-6e2f-4649-9961-e510cbc4a9a2",
            "platform": "meta",
            "account_id": "act_123",
        },
        "client": {"name": "Test", "vertical": "ecommerce"},
        "campaign_id_map": {},
    }

    result = await graph.analista_node(state)
    campaign = result["campaigns_analyzed"][0]

    assert campaign["revenue_real"] == 500.0
    assert campaign["leads_total"] == 2
    assert campaign["deals_closed"] == 1
    assert campaign["roas_real"] == 5.0


def test_get_leads_endpoint_returns_lead(mocker, client):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")
    fake_supabase = mocker.patch("api.routers.leads.supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value
    ).data = [
        {
            "id": "lead-uuid-1",
            "crm_deal_id": "deal-99",
            "campaign_id": CAMPAIGN_UUID,
            "client_id": "922f2273-6e2f-4649-9961-e510cbc4a9a2",
        }
    ]

    response = client.get(
        "/leads?crm_deal_id=deal-99",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "lead-uuid-1"
    assert response.json()["campaign_id"] == CAMPAIGN_UUID


def test_get_leads_endpoint_empty_when_not_found(mocker, client):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")
    fake_supabase = mocker.patch("api.routers.leads.supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value
    ).data = []

    response = client.get(
        "/leads?crm_deal_id=missing-deal",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json() == {}


def test_get_leads_endpoint_rejects_bad_api_key(mocker, client):
    from agent.config import settings

    mocker.patch.object(settings, "api_secret_key", "test-key")

    response = client.get(
        "/leads?crm_deal_id=deal-99",
        headers={"X-API-Key": "wrong"},
    )

    assert response.status_code == 403
