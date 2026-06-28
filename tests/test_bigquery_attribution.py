from __future__ import annotations

import json

import pytest

import agent.graph as graph
from agent.tools import bigquery_attribution

CAMPAIGN_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"
EXTERNAL_ID = "120249189080650247"


def test_get_campaign_real_roas_invalid_returns_empty():
    assert bigquery_attribution.get_campaign_real_roas("n/a") == {
        "roas_real": None,
        "roas_plataforma": None,
        "revenue_real": 0.0,
        "leads_total": 0,
        "deals_closed": 0,
        "total_spend": 0,
    }


def test_get_campaign_real_roas_reads_bigquery(mocker):
    fake_row = {
        "roas_real": 3.2,
        "roas_plataforma": 1.4,
        "revenue_real": 3200.0,
        "leads_total": 12,
        "deals_closed": 4,
        "total_spend": 1000.0,
    }
    fake_client = mocker.Mock()
    fake_client.query.return_value.result.return_value = [fake_row]
    mocker.patch.object(bigquery_attribution, "_get_bq_client", return_value=fake_client)

    result = bigquery_attribution.get_campaign_real_roas(CAMPAIGN_UUID)

    assert result == fake_row
    fake_client.query.assert_called_once()
    query = fake_client.query.call_args.args[0]
    assert "campaign_real_roas" in query
    assert "WHERE campaign_id = @campaign_id" in query


def test_get_campaign_real_roas_fallback_supabase(mocker):
    mocker.patch.object(
        bigquery_attribution,
        "_get_bq_client",
        side_effect=RuntimeError("bigquery unavailable"),
    )
    fake_supabase = mocker.Mock()
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value
    ).data = {
        "revenue_closed": "2500.50",
        "leads_total": 9,
        "deals_closed": 3,
    }
    mocker.patch("agent.tools.supabase_client.get_supabase", return_value=fake_supabase)

    result = bigquery_attribution.get_campaign_real_roas(CAMPAIGN_UUID)

    assert result["roas_real"] is None
    assert result["revenue_real"] == 2500.50
    assert result["leads_total"] == 9
    assert result["deals_closed"] == 3
    fake_supabase.table.assert_called_once_with("campaign_attribution")


def test_sync_campaign_spend_to_bq_inserts_rows(mocker):
    fake_client = mocker.Mock()
    fake_client.insert_rows_json.return_value = []
    mocker.patch.object(bigquery_attribution, "_get_bq_client", return_value=fake_client)

    bigquery_attribution.sync_campaign_spend_to_bq(
        [
            {
                "_uuid": CAMPAIGN_UUID,
                "campaign_id": EXTERNAL_ID,
                "platform": "meta",
                "last_spend_usd": 123.45,
                "avg_roas_click": 2.4,
            }
        ]
    )

    fake_client.insert_rows_json.assert_called_once()
    rows = fake_client.insert_rows_json.call_args.args[1]
    assert rows[0]["campaign_id"] == CAMPAIGN_UUID
    assert rows[0]["external_campaign_id"] == EXTERNAL_ID
    assert rows[0]["spend"] == 123.45
    assert rows[0]["platform_roas"] == 2.4


def test_sync_campaign_spend_to_bq_never_blocks_cycle(mocker):
    fake_client = mocker.Mock()
    fake_client.insert_rows_json.side_effect = RuntimeError("insert failed")
    mocker.patch.object(bigquery_attribution, "_get_bq_client", return_value=fake_client)

    bigquery_attribution.sync_campaign_spend_to_bq(
        [{"_uuid": CAMPAIGN_UUID, "campaign_id": EXTERNAL_ID}]
    )

    fake_client.insert_rows_json.assert_called_once()


@pytest.mark.asyncio
async def test_analista_node_enriches_real_attribution(mocker):
    mocker.patch.object(graph, "_sync_campaign_registry", return_value={EXTERNAL_ID: CAMPAIGN_UUID})
    mocker.patch.object(
        graph,
        "_agent_loop",
        return_value=json.dumps(
            {
                "campaigns_analyzed": [
                    {
                        "campaign_id": EXTERNAL_ID,
                        "name": "Campanha Meta",
                        "platform": "meta",
                        "last_spend_usd": 100.0,
                    }
                ],
                "anomalies": [
                    {
                        "campaign_id": EXTERNAL_ID,
                        "name": "Campanha Meta",
                        "platform": "meta",
                        "anomaly_type": "roas_negative",
                    }
                ],
            }
        ),
    )
    mocker.patch.object(
        graph,
        "get_campaign_real_roas",
        return_value={
            "roas_real": 4.1,
            "roas_plataforma": 1.2,
            "revenue_real": 410.0,
            "leads_total": 5,
            "deals_closed": 2,
            "total_spend": 100.0,
        },
    )
    sync = mocker.patch.object(graph, "sync_campaign_spend_to_bq")

    result = await graph.analista_node(
        {
            "account": {
                "id": "922f2273-6e2f-4649-9961-e510cbc4a9a2",
                "platform": "meta",
                "account_id": "act_123",
            },
            "client": {"name": "Cliente", "vertical": "ecommerce"},
            "campaign_id_map": {},
        }
    )

    campaign = result["campaigns_analyzed"][0]
    anomaly = result["anomalies"][0]
    assert campaign["_uuid"] == CAMPAIGN_UUID
    assert campaign["roas_real"] == 4.1
    assert campaign["revenue_real"] == 410.0
    assert campaign["deals_closed"] == 2
    assert anomaly["roas_real"] == 4.1
    sync.assert_called_once_with(result["campaigns_analyzed"])
