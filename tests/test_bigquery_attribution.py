"""
Testes da camada de attribution (BigQuery + fallback Supabase).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.tools import bigquery_attribution as bq_attr

VALID_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"


@pytest.fixture(autouse=True)
def _reset_bq_client():
    bq_attr._bq_client = None
    yield
    bq_attr._bq_client = None


def test_get_campaign_real_roas_invalid_uuid_returns_empty():
    result = bq_attr.get_campaign_real_roas("n/a")
    assert result == bq_attr._empty_attribution()
    assert result["revenue_real"] == 0.0
    assert result["deals_closed"] == 0


def test_get_campaign_real_roas_empty_string_returns_empty():
    result = bq_attr.get_campaign_real_roas("")
    assert result["roas_real"] is None
    assert result["leads_total"] == 0


def test_get_campaign_real_roas_from_bigquery(mocker):
    mock_client = MagicMock()
    mock_client.query.return_value.result.return_value = [{
        "roas_real": 3.5,
        "roas_plataforma": 2.1,
        "revenue_real": 7000.0,
        "leads_total": 12,
        "deals_closed": 4,
        "total_spend": 2000.0,
    }]
    mocker.patch.object(bq_attr, "_get_bq_client", return_value=mock_client)

    result = bq_attr.get_campaign_real_roas(VALID_UUID)

    assert result["roas_real"] == 3.5
    assert result["revenue_real"] == 7000.0
    assert result["deals_closed"] == 4
    mock_client.query.assert_called_once()


def test_get_campaign_real_roas_falls_back_to_supabase(mocker):
    mocker.patch.object(
        bq_attr,
        "_get_bq_client",
        side_effect=Exception("BigQuery unavailable"),
    )
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "revenue_closed": 1500.0,
        "leads_total": 8,
        "deals_closed": 2,
    }
    mocker.patch("agent.tools.supabase_client.get_supabase", return_value=mock_sb)

    result = bq_attr.get_campaign_real_roas(VALID_UUID)

    assert result["roas_real"] is None
    assert result["revenue_real"] == 1500.0
    assert result["leads_total"] == 8
    assert result["deals_closed"] == 2
    mock_sb.table.assert_called_with("campaign_attribution")


def test_get_campaign_real_roas_bq_empty_rows_returns_empty(mocker):
    mock_client = MagicMock()
    mock_client.query.return_value.result.return_value = []
    mocker.patch.object(bq_attr, "_get_bq_client", return_value=mock_client)

    result = bq_attr.get_campaign_real_roas(VALID_UUID)

    assert result == bq_attr._empty_attribution()


def test_sync_campaign_spend_to_bq_inserts_rows(mocker):
    mock_client = MagicMock()
    mock_client.insert_rows_json.return_value = []
    mocker.patch.object(bq_attr, "_get_bq_client", return_value=mock_client)

    campaigns = [
        {
            "_uuid": VALID_UUID,
            "campaign_id": "120249189080650247",
            "platform": "meta",
            "last_spend_usd": 45.0,
            "avg_roas_click": 2.1,
        }
    ]
    bq_attr.sync_campaign_spend_to_bq(campaigns)

    mock_client.insert_rows_json.assert_called_once()
    rows = mock_client.insert_rows_json.call_args.args[1]
    assert len(rows) == 1
    assert rows[0]["campaign_id"] == VALID_UUID
    assert rows[0]["spend"] == 45.0


def test_sync_campaign_spend_to_bq_empty_list_noop(mocker):
    mock_client = MagicMock()
    mocker.patch.object(bq_attr, "_get_bq_client", return_value=mock_client)

    bq_attr.sync_campaign_spend_to_bq([])

    mock_client.insert_rows_json.assert_not_called()


def test_sync_campaign_spend_to_bq_failure_silent(mocker):
    mocker.patch.object(
        bq_attr,
        "_get_bq_client",
        side_effect=Exception("connection refused"),
    )
    bq_attr.sync_campaign_spend_to_bq([{"_uuid": VALID_UUID, "campaign_id": "1"}])


def test_sync_campaign_spend_to_bq_skips_without_uuid(mocker):
    mock_client = MagicMock()
    mocker.patch.object(bq_attr, "_get_bq_client", return_value=mock_client)

    bq_attr.sync_campaign_spend_to_bq([{"campaign_id": "1", "platform": "meta"}])

    mock_client.insert_rows_json.assert_not_called()
