"""
Testes: guard de UUID inválido nos tools do agent/graph.py

Cobre:
- fetch_account_campaigns retorna [] sem tocar Supabase para UUIDs inválidos
- fetch_daily_metrics retorna [] para UUIDs inválidos
- fetch_meta_campaigns_live retorna [] para UUIDs inválidos
- fetch_meta_insights_live retorna {} para UUIDs inválidos
- analista_node retorna early sem campanha para account["id"] inválido
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper — constrói state mínimo para o analista_node
# ---------------------------------------------------------------------------
def _make_state(account_id: str | None = "valid-uuid-1234") -> dict:
    return {
        "account": {
            "id": account_id,
            "account_id": "ext-001",
            "platform": "meta",
        },
        "client": {"name": "Acme", "vertical": "ecommerce", "business_dna": {}},
        "campaigns_analyzed": [],
        "anomalies": [],
        "decision": {},
        "memory_context": [],
        "risk_level": "",
        "risk_reasoning": "",
        "execution_result": {},
    }


# ---------------------------------------------------------------------------
# fetch_account_campaigns — guard de UUID
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_uuid", ["None", "n/a", "null", "undefined", "", None])
async def test_fetch_account_campaigns_invalid_uuid_returns_empty(bad_uuid):
    """Não deve chamar Supabase quando o UUID é inválido."""
    from agent.graph import fetch_account_campaigns

    with patch("agent.graph.supabase") as mock_supabase:
        result = await fetch_account_campaigns.ainvoke({"ad_account_uuid": bad_uuid or ""})

    assert result == []
    mock_supabase.table.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_account_campaigns_valid_uuid_calls_supabase():
    """Com UUID válido deve consultar o Supabase."""
    from agent.graph import fetch_account_campaigns

    mock_chain = MagicMock()
    mock_chain.execute.return_value = MagicMock(data=[{"id": "camp-1"}])

    with patch("agent.graph.supabase") as mock_supabase:
        mock_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value = mock_chain
        result = await fetch_account_campaigns.ainvoke({"ad_account_uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"})

    assert result == [{"id": "camp-1"}]
    mock_supabase.table.assert_called_once_with("campaigns")


# ---------------------------------------------------------------------------
# fetch_daily_metrics — guard de UUID
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_uuid", ["None", "n/a", ""])
async def test_fetch_daily_metrics_invalid_uuid_returns_empty(bad_uuid):
    from agent.graph import fetch_daily_metrics

    with patch("agent.graph.supabase") as mock_supabase:
        result = await fetch_daily_metrics.ainvoke({"campaign_uuid": bad_uuid, "platform": "meta"})

    assert result == []
    mock_supabase.table.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_meta_campaigns_live — guard de UUID
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_uuid", ["None", "n/a", ""])
async def test_fetch_meta_campaigns_live_invalid_uuid_returns_empty(bad_uuid):
    from agent.graph import fetch_meta_campaigns_live

    with patch("agent.graph.supabase") as mock_supabase:
        result = await fetch_meta_campaigns_live.ainvoke({"ad_account_uuid": bad_uuid})

    assert result == []
    mock_supabase.table.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_meta_insights_live — guard de UUID
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_uuid", ["None", "n/a", ""])
async def test_fetch_meta_insights_live_invalid_uuid_returns_empty(bad_uuid):
    from agent.graph import fetch_meta_insights_live

    with patch("agent.graph.supabase") as mock_supabase:
        result = await fetch_meta_insights_live.ainvoke({
            "ad_account_uuid": bad_uuid,
            "campaign_external_id": "camp-ext-1",
            "date_start": "2026-06-01",
            "date_end": "2026-06-07",
        })

    assert result == {}
    mock_supabase.table.assert_not_called()


# ---------------------------------------------------------------------------
# analista_node — guard de account["id"] inválido
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [None, "None", "n/a", ""])
async def test_analista_node_invalid_account_id_returns_early(bad_id):
    """analista_node deve retornar listas vazias sem chamar o LLM se account.id for inválido."""
    from agent.graph import analista_node

    state = _make_state(account_id=bad_id)

    with patch("agent.graph._agent_loop", new_callable=AsyncMock) as mock_loop:
        result = await analista_node(state)

    assert result == {"campaigns_analyzed": [], "anomalies": []}
    mock_loop.assert_not_called()
