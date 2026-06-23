"""
Testes determinísticos (sem LLM / sem APIs externas) para:

FIX #1 — guarda anti-UUID inválido ("n/a") no estrategista/executor.
FIX #2 — Google Agent com modo somente-leitura e wiring no ciclo.

Tudo mockado: não requer Anthropic, Google Ads nem Supabase real.
"""
from __future__ import annotations

import pytest

import agent.graph as graph
import agent.run as run_module
import agent.graphs.google_agent as google_agent
import agent.tools.google_ads as google_ads_tools
from agent.graph import (
    _is_invalid_uuid,
    _recover_campaign_uuid,
    fetch_daily_metrics,
    fetch_account_campaigns,
    is_invalid_uuid,
    is_valid_uuid,
    run_google_action,
    save_decision,
    save_memory,
)

VALID_UUID = "922f2273-6e2f-4649-9961-e510cbc4a9a2"
VALID_UUID_2 = "f888f617-1692-4d9d-852f-a9d46a02b917"
META_NUMERIC_CAMPAIGN_ID = "120249189080650247"


# ---------------------------------------------------------------------------
# FIX #1 — validação de UUID
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (VALID_UUID, True),
        ("n/a", False),
        ("N/A", False),
        ("", False),
        ("   ", False),
        (None, False),
        (123, False),
        (META_NUMERIC_CAMPAIGN_ID, False),
        ("not-a-uuid", False),
        ("120249189080650247", False),  # Meta campaign_id numérico — não é UUID interno
    ],
)
def test_is_valid_uuid(value, expected):
    assert is_valid_uuid(value) is expected


@pytest.mark.parametrize(
    "value,expected_invalid",
    [
        (META_NUMERIC_CAMPAIGN_ID, True),
        (VALID_UUID, False),
        (VALID_UUID_2, False),
        ("n/a", True),
        ("None", True),
    ],
)
def test_is_invalid_uuid(value, expected_invalid):
    assert _is_invalid_uuid(value) is expected_invalid
    assert is_invalid_uuid(value) is expected_invalid


@pytest.mark.asyncio
async def test_fetch_daily_metrics_skips_invalid_campaign_uuid(mocker):
    """fetch_daily_metrics não deve consultar Supabase com ID numérico do Meta."""
    fake_supabase = mocker.patch.object(graph, "supabase")
    log_spy = mocker.spy(graph.log, "warning")

    result = await fetch_daily_metrics.ainvoke(
        {"campaign_uuid": "120249189080650247", "platform": "meta", "days": 7}
    )

    assert result == []
    fake_supabase.table.assert_not_called()
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "fetch_daily_metrics.skip" in events


@pytest.mark.asyncio
async def test_fetch_daily_metrics_queries_with_valid_uuid(mocker):
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value
    ).data = [{"date": "2026-06-01", "spend": 10}]

    out = await fetch_daily_metrics.ainvoke(
        {"campaign_uuid": VALID_UUID, "platform": "meta", "days": 7}
    )

    fake_supabase.table.assert_called_once_with("daily_metrics")
    assert len(out) == 1


@pytest.mark.asyncio
async def test_save_decision_skips_invalid_uuid(mocker):
    """save_decision não deve tocar o banco quando o UUID é inválido."""
    fake_supabase = mocker.patch.object(graph, "supabase")

    result = await save_decision.ainvoke(
        {
            "campaign_uuid": "n/a",
            "action_type": "budget_decrease",
            "reasoning": "teste",
            "payload": {},
            "executed": False,
        }
    )

    assert result["skipped"] is True
    assert result["reason"] == "invalid_campaign_uuid"
    fake_supabase.table.assert_not_called()  # nenhum INSERT tentado


@pytest.mark.asyncio
async def test_save_decision_inserts_with_valid_uuid(mocker):
    """Com UUID válido, save_decision faz o INSERT normalmente."""
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.insert.return_value.execute.return_value
    ).data = [{"id": "dec-1", "campaign_id": VALID_UUID}]

    result = await save_decision.ainvoke(
        {
            "campaign_uuid": VALID_UUID,
            "action_type": "monitor_only",
            "reasoning": "ok",
            "payload": {"x": 1},
            "executed": False,
        }
    )

    fake_supabase.table.assert_called_once_with("agent_decisions")
    assert result["id"] == "dec-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["None", "n/a", "", META_NUMERIC_CAMPAIGN_ID])
async def test_fetch_account_campaigns_skips_invalid_ad_account_uuid(mocker, value):
    """fetch_account_campaigns não deve consultar UUID inválido no Supabase."""
    fake_supabase = mocker.patch.object(graph, "supabase")
    log_spy = mocker.spy(graph.log, "warning")

    result = await fetch_account_campaigns.ainvoke({"ad_account_uuid": value})

    assert result == []
    fake_supabase.table.assert_not_called()
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "fetch_campaigns.skip" in events


@pytest.mark.asyncio
async def test_fetch_daily_metrics_skips_numeric_meta_campaign_id(mocker):
    """fetch_daily_metrics não deve enviar ID numérico Meta para coluna uuid."""
    fake_supabase = mocker.patch.object(graph, "supabase")
    log_spy = mocker.spy(graph.log, "warning")

    result = await fetch_daily_metrics.ainvoke(
        {"campaign_uuid": META_NUMERIC_CAMPAIGN_ID, "platform": "meta"}
    )

    assert result == []
    fake_supabase.table.assert_not_called()
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "fetch_daily_metrics.skip" in events


def test_recover_campaign_uuid_by_external_id():
    decision = {"campaign_id": "EXT-1", "campaign_name": "Camp A"}
    anomalies = [
        {"campaign_uuid": "bad", "campaign_id": "EXT-9"},
        {"campaign_uuid": VALID_UUID, "campaign_id": "EXT-1"},
    ]
    assert _recover_campaign_uuid(decision, anomalies) == VALID_UUID


def test_recover_campaign_uuid_single_fallback():
    decision = {"campaign_id": "n/a", "campaign_name": ""}
    anomalies = [{"campaign_uuid": VALID_UUID, "campaign_id": "X"}]
    assert _recover_campaign_uuid(decision, anomalies) == VALID_UUID


def test_recover_campaign_uuid_none_when_ambiguous():
    decision = {"campaign_id": "nope", "campaign_name": "nope"}
    anomalies = [
        {"campaign_uuid": VALID_UUID, "campaign_id": "A"},
        {"campaign_uuid": VALID_UUID_2, "campaign_id": "B"},
    ]
    assert _recover_campaign_uuid(decision, anomalies) is None


@pytest.mark.asyncio
async def test_save_memory_nulls_numeric_campaign_uuid(mocker):
    """save_memory grava memória global quando campaign_uuid veio como ID externo Meta."""
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.insert.return_value.execute.return_value
    ).data = [{"id": "mem-1", "campaign_id": None}]

    result = await save_memory.ainvoke(
        {
            "content": "campanha com ID externo Meta",
            "memory_type": "observation",
            "campaign_uuid": META_NUMERIC_CAMPAIGN_ID,
        }
    )

    inserted = fake_supabase.table.return_value.insert.call_args.args[0]
    assert inserted["campaign_id"] is None
    assert result["id"] == "mem-1"


# ---------------------------------------------------------------------------
# FIX #2 — Google read-only e wiring
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_google_action_read_only_does_not_call_api(mocker):
    """Em read-only, run_google_action NÃO chama a API Google nem o Supabase."""
    mocker.patch.object(graph.settings, "google_ads_read_only", True)
    fake_google = mocker.patch.object(graph, "google_ads")
    fake_supabase = mocker.patch.object(graph, "supabase")

    result = await run_google_action.ainvoke(
        {
            "action_type": "pause_campaign",
            "customer_id": "1224681784",
            "campaign_external_id": "555",
            "account_external_id": "1224681784",
        }
    )

    assert result["read_only"] is True
    assert result["executed"] is False
    fake_google.pause_campaign.assert_not_called()
    fake_supabase.table.assert_not_called()


@pytest.mark.asyncio
async def test_run_google_action_executes_when_not_read_only(mocker):
    """Com read-only desligado, a ação é despachada para a API Google."""
    mocker.patch.object(graph.settings, "google_ads_read_only", False)
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value
    ).data = {"token": "refresh-xyz"}
    fake_google = mocker.patch.object(graph, "google_ads")

    async def _ok(*a, **k):
        return {"status": "paused"}

    fake_google.pause_campaign.side_effect = _ok

    result = await run_google_action.ainvoke(
        {
            "action_type": "pause_campaign",
            "customer_id": "1224681784",
            "campaign_external_id": "555",
            "account_external_id": "1224681784",
        }
    )

    fake_google.pause_campaign.assert_called_once()
    assert result == {"status": "paused"}


@pytest.mark.asyncio
async def test_fetch_google_campaigns_live_logs_start(mocker):
    """fetch_google_campaigns_live emite google.list_campaigns.start e usa get_campaigns."""
    fake_google = mocker.patch.object(graph, "google_ads")

    async def _campaigns(customer_id, creds):
        return [{"campaign_id": "1", "name": "C1"}]

    fake_google.get_campaigns.side_effect = _campaigns
    log_spy = mocker.spy(graph.log, "info")

    out = await graph.fetch_google_campaigns_live.ainvoke({"customer_id": "1224681784"})

    assert out == [{"campaign_id": "1", "name": "C1"}]
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "google.list_campaigns.start" in events


@pytest.mark.asyncio
async def test_fetch_account_campaigns_skips_invalid_uuid(mocker):
    """fetch_account_campaigns não consulta o Supabase com UUID inválido."""
    fake_supabase = mocker.patch.object(graph, "supabase")
    log_spy = mocker.spy(graph.log, "warning")

    for bad in ("None", "n/a", "", None, META_NUMERIC_CAMPAIGN_ID):
        fake_supabase.reset_mock()
        out = await graph.fetch_account_campaigns.ainvoke({"ad_account_uuid": bad})
        assert out == []
        fake_supabase.table.assert_not_called()

    log_spy.assert_called()
    assert any(c.args[0] == "fetch_campaigns.skip" for c in log_spy.call_args_list)


@pytest.mark.asyncio
async def test_fetch_account_campaigns_queries_with_valid_uuid(mocker):
    fake_supabase = mocker.patch.object(graph, "supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value
    ).data = [{"id": VALID_UUID, "name": "Camp A"}]

    out = await graph.fetch_account_campaigns.ainvoke({"ad_account_uuid": VALID_UUID})

    fake_supabase.table.assert_called_once_with("campaigns")
    assert out == [{"id": VALID_UUID, "name": "Camp A"}]


@pytest.mark.asyncio
async def test_run_google_agent_skips_without_customer_id(mocker):
    mocker.patch.object(google_agent.settings, "google_ads_customer_id", "")
    invoke = mocker.patch.object(google_agent.compiled_graph, "ainvoke")

    result = await google_agent.run_google_agent()

    invoke.assert_not_called()
    assert result["skipped"] is True
    assert result["reason"] == "no_customer_id"


@pytest.mark.asyncio
async def test_run_google_agent_synthesizes_from_env(mocker):
    """Sem conta no Supabase, sintetiza do .env e roda o grafo (read-only)."""
    mocker.patch.object(google_agent.settings, "google_ads_customer_id", "1224681784")
    mocker.patch.object(google_agent.settings, "google_ads_refresh_token", "refresh-xyz")
    mocker.patch.object(google_agent.settings, "google_ads_read_only", True)
    mocker.patch.object(google_agent, "_fetch_google_accounts", return_value=[])
    mocker.patch.object(
        google_agent, "_resolve_default_client", return_value={"name": "Cajé", "business_dna": {}}
    )

    captured = {}

    async def _ainvoke(state):
        captured["state"] = state
        return state

    mocker.patch.object(google_agent.compiled_graph, "ainvoke", side_effect=_ainvoke)

    result = await google_agent.run_google_agent()

    account = captured["state"]["account"]
    assert account["platform"] == "google"
    assert account["account_id"] == "1224681784"  # vem do .env, não hardcoded
    assert account["token"] == "refresh-xyz"
    assert account["id"] == ""
    assert result["skipped"] is False
    assert result["source"] == "env"
    assert result["accounts_processed"] == 1


@pytest.mark.asyncio
async def test_run_all_accounts_logs_google_agent_start_and_done(mocker):
    """run.py deve chamar o Google Agent e emitir os logs exigidos quando há customer_id."""
    mocker.patch.object(run_module.settings, "google_ads_customer_id", " 1224681784 ")
    (
        mocker.patch.object(run_module, "supabase")
        .table.return_value.select.return_value.eq.return_value.execute.return_value
    ).data = []
    google_result = {"skipped": False, "source": "env", "accounts_processed": 1}
    run_google = mocker.patch.object(
        run_module, "run_google_agent", return_value=google_result
    )
    log_spy = mocker.spy(run_module.log, "info")

    await run_module.run_all_accounts()

    run_google.assert_called_once()
    events = [c.args[0] for c in log_spy.call_args_list if c.args]
    assert "google.agent.start" in events
    assert "google.agent.done" in events


def test_google_ads_client_uses_settings_login_customer_id(mocker):
    mocker.patch.object(google_ads_tools.settings, "google_ads_developer_token", "dev-token")
    mocker.patch.object(google_ads_tools.settings, "google_ads_login_customer_id", "1234567890")
    load = mocker.patch.object(
        google_ads_tools.GoogleAdsClient,
        "load_from_dict",
        return_value=object(),
    )

    google_ads_tools._build_client(
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "refresh-token",
        }
    )

    config = load.call_args.args[0]
    assert config["login_customer_id"] == "1234567890"
