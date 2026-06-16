"""
Testes do auto-registro de campanhas no Supabase (campaign_registry).
"""
from __future__ import annotations

import pytest

import agent.graph as graph
from agent.graph import (
    fetch_daily_metrics,
    resolve_campaign_uuid,
    save_memory,
)
from agent.tools import campaign_registry

ACCOUNT_UUID = "922f2273-6e2f-4649-9961-e510cbc4a9a2"
CAMPAIGN_UUID = "f888f617-1692-4d9d-852f-a9d46a02b917"
CAMPAIGN_UUID_2 = "a1b2c3d4-e5f6-4789-a012-3456789abcde"
EXTERNAL_ID = "120249189080650247"
EXTERNAL_ID_2 = "120249189080650248"


def _campaigns_table(fake_supabase):
    return fake_supabase.table.return_value


@pytest.fixture(autouse=True)
def _reset_campaign_map():
    campaign_registry.set_campaign_id_map({})
    yield
    campaign_registry.set_campaign_id_map({})


@pytest.mark.asyncio
async def test_upsert_campaigns_creates_new(mocker):
    fake_supabase = mocker.patch.object(campaign_registry, "supabase")
    select_chain = _campaigns_table(fake_supabase).select.return_value
    select_chain.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    insert_chain = _campaigns_table(fake_supabase).insert.return_value
    insert_chain.execute.return_value.data = [
        {"id": CAMPAIGN_UUID, "campaign_id": EXTERNAL_ID}
    ]

    campaigns = [
        {
            "campaign_id": EXTERNAL_ID,
            "name": "Campanha Nova",
            "status": "ACTIVE",
            "objective": "CONVERSIONS",
            "daily_budget_usd": 50.0,
        }
    ]

    id_map = await campaign_registry.upsert_campaigns(
        ACCOUNT_UUID, campaigns, "meta", account_external_id="act_123"
    )

    assert id_map == {EXTERNAL_ID: CAMPAIGN_UUID}
    _campaigns_table(fake_supabase).insert.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_campaigns_updates_existing(mocker):
    fake_supabase = mocker.patch.object(campaign_registry, "supabase")
    select_chain = _campaigns_table(fake_supabase).select.return_value
    select_chain.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": CAMPAIGN_UUID}
    ]
    update_chain = _campaigns_table(fake_supabase).update.return_value
    update_chain.eq.return_value.execute.return_value.data = [{"id": CAMPAIGN_UUID}]

    campaigns = [
        {
            "campaign_id": EXTERNAL_ID,
            "name": "Campanha Atualizada",
            "status": "PAUSED",
            "objective": "REACH",
            "daily_budget_usd": 75.0,
        }
    ]

    id_map = await campaign_registry.upsert_campaigns(
        ACCOUNT_UUID, campaigns, "meta", account_external_id="act_123"
    )

    assert id_map == {EXTERNAL_ID: CAMPAIGN_UUID}
    _campaigns_table(fake_supabase).update.assert_called_once()
    _campaigns_table(fake_supabase).insert.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_campaigns_returns_map_for_multiple(mocker):
    fake_supabase = mocker.patch.object(campaign_registry, "supabase")

    def _select_execute():
        chain = _campaigns_table(fake_supabase).select.return_value
        return chain.eq.return_value.eq.return_value.limit.return_value.execute

    execute = _select_execute()
    execute.side_effect = [
        mocker.Mock(data=[]),
        mocker.Mock(data=[{"id": CAMPAIGN_UUID}]),
    ]

    insert_chain = _campaigns_table(fake_supabase).insert.return_value
    insert_chain.execute.return_value.data = [{"id": CAMPAIGN_UUID_2}]

    update_chain = _campaigns_table(fake_supabase).update.return_value
    update_chain.eq.return_value.execute.return_value.data = [{"id": CAMPAIGN_UUID}]

    campaigns = [
        {"campaign_id": EXTERNAL_ID, "name": "Nova", "status": "ACTIVE"},
        {"campaign_id": EXTERNAL_ID_2, "name": "Existente", "status": "PAUSED"},
    ]

    id_map = await campaign_registry.upsert_campaigns(ACCOUNT_UUID, campaigns, "google")

    assert id_map[EXTERNAL_ID] == CAMPAIGN_UUID_2
    assert id_map[EXTERNAL_ID_2] == CAMPAIGN_UUID
    assert len(id_map) == 2


@pytest.mark.asyncio
async def test_register_campaigns_safe_does_not_raise_on_error(mocker):
    mocker.patch.object(
        campaign_registry,
        "upsert_campaigns",
        side_effect=RuntimeError("db down"),
    )
    log_spy = mocker.spy(campaign_registry.log, "warning")

    result = await campaign_registry.register_campaigns_safe(
        ACCOUNT_UUID,
        [{"campaign_id": EXTERNAL_ID, "name": "X", "status": "ACTIVE"}],
        "meta",
    )

    assert result == {}
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "campaign_registry.upsert_failed" in events


def test_resolve_campaign_uuid_from_map():
    campaign_registry.set_campaign_id_map({EXTERNAL_ID: CAMPAIGN_UUID})

    assert resolve_campaign_uuid(EXTERNAL_ID) == CAMPAIGN_UUID
    assert resolve_campaign_uuid(CAMPAIGN_UUID) == CAMPAIGN_UUID


@pytest.mark.asyncio
async def test_fetch_daily_metrics_uses_resolved_uuid(mocker):
    campaign_registry.set_campaign_id_map({EXTERNAL_ID: CAMPAIGN_UUID})
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value
    ).data = [{"date": "2026-06-01", "spend": 10}]
    log_spy = mocker.spy(graph.log, "info")

    result = await fetch_daily_metrics.ainvoke(
        {"campaign_uuid": EXTERNAL_ID, "platform": "meta", "days": 7}
    )

    assert len(result) == 1
    eq_call = fake_supabase.table.return_value.select.return_value.eq
    eq_call.assert_called_once_with("campaign_id", CAMPAIGN_UUID)
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "fetch_daily_metrics.start" in events
    assert any(
        c.kwargs.get("campaign_uuid") == CAMPAIGN_UUID
        for c in log_spy.call_args_list
        if c.args and c.args[0] == "fetch_daily_metrics.start"
    )


@pytest.mark.asyncio
async def test_save_memory_uses_resolved_uuid(mocker):
    campaign_registry.set_campaign_id_map({EXTERNAL_ID: CAMPAIGN_UUID})
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.insert.return_value.execute.return_value
    ).data = [{"id": "mem-1", "campaign_id": CAMPAIGN_UUID}]
    log_spy = mocker.spy(graph.log, "info")

    await save_memory.ainvoke(
        {
            "content": "observação com UUID real",
            "memory_type": "observation",
            "campaign_uuid": EXTERNAL_ID,
        }
    )

    inserted = fake_supabase.table.return_value.insert.call_args.args[0]
    assert inserted["campaign_id"] == CAMPAIGN_UUID
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "memorizador.memory_saved" in events
    assert any(
        c.kwargs.get("campaign_uuid") == CAMPAIGN_UUID
        for c in log_spy.call_args_list
        if c.args and c.args[0] == "memorizador.memory_saved"
    )


@pytest.mark.asyncio
async def test_fetch_meta_campaigns_live_registers_campaigns(mocker):
    fake_supabase = mocker.patch.object(graph, "supabase")
    fake_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "account_id": "act_123",
        "token": "token-abc",
    }
    mocker.patch.object(
        graph.meta_ads,
        "list_campaigns",
        return_value=[{"campaign_id": EXTERNAL_ID, "name": "Meta Camp", "status": "ACTIVE"}],
    )
    register = mocker.patch.object(
        graph,
        "register_campaigns_safe",
        return_value={EXTERNAL_ID: CAMPAIGN_UUID},
    )

    out = await graph.fetch_meta_campaigns_live.ainvoke({"ad_account_uuid": ACCOUNT_UUID})

    register.assert_awaited_once()
    assert out[0]["campaign_uuid"] == CAMPAIGN_UUID
