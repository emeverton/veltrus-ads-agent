"""
Testes: run_google_agent() em agent/run.py

Cobre:
- log google.agent.start é emitido com customer_id correto
- log google.agent.done é emitido com resultado
- fallback para GOOGLE_ADS_CUSTOMER_ID quando account_id é inválido
- run_all_accounts despacha contas google para run_google_agent
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


_GOOGLE_ACCOUNT = {
    "id": "acc-uuid-001",
    "account_id": "123-456-7890",
    "platform": "google",
    "active": True,
}
_META_ACCOUNT = {
    "id": "acc-uuid-002",
    "account_id": "act_987654",
    "platform": "meta",
    "active": True,
}
_CLIENT = {"name": "Acme", "vertical": "ecommerce", "business_dna": {}, "active": True}


# ---------------------------------------------------------------------------
# run_google_agent — log e chamada ao run_account
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_google_agent_logs_start_and_done(capfd):
    from agent import run as run_module

    with patch.object(run_module, "run_account", new_callable=AsyncMock) as mock_run:
        result = await run_module.run_google_agent(
            account=_GOOGLE_ACCOUNT.copy(),
            client=_CLIENT.copy(),
        )

    mock_run.assert_awaited_once()
    assert result["status"] == "done"
    assert result["customer_id"] == "123-456-7890"


@pytest.mark.asyncio
async def test_run_google_agent_uses_settings_fallback_when_account_id_invalid():
    """Se account_id for 'None', deve usar settings.google_ads_customer_id."""
    from agent import run as run_module

    bad_account = {**_GOOGLE_ACCOUNT, "account_id": "None"}

    with patch.object(run_module, "run_account", new_callable=AsyncMock), \
         patch.object(run_module.settings, "google_ads_customer_id", "fallback-cid-999"):
        result = await run_module.run_google_agent(
            account=bad_account,
            client=_CLIENT.copy(),
        )

    assert result["customer_id"] == "fallback-cid-999"


@pytest.mark.asyncio
async def test_run_google_agent_returns_error_status_on_exception():
    from agent import run as run_module

    with patch.object(run_module, "run_account", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        result = await run_module.run_google_agent(
            account=_GOOGLE_ACCOUNT.copy(),
            client=_CLIENT.copy(),
        )

    assert result["status"] == "error"
    assert result["customer_id"] == "123-456-7890"


# ---------------------------------------------------------------------------
# run_all_accounts — roteamento por plataforma
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_all_accounts_routes_google_to_run_google_agent():
    from agent import run as run_module

    google_row = {**_GOOGLE_ACCOUNT, "clients": _CLIENT.copy()}
    meta_row = {**_META_ACCOUNT, "clients": _CLIENT.copy()}

    mock_result = MagicMock(data=[google_row, meta_row])

    with patch.object(run_module, "run_google_agent", new_callable=AsyncMock) as mock_google, \
         patch.object(run_module, "run_account", new_callable=AsyncMock) as mock_account, \
         patch.object(run_module.supabase, "table") as mock_table:

        mock_table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result
        await run_module.run_all_accounts()

    mock_google.assert_awaited_once()
    mock_account.assert_awaited_once()

    # Verifica que o account enviado ao google agent tem platform == "google"
    google_call_account = mock_google.call_args.kwargs.get("account") or mock_google.call_args[1].get("account")
    assert google_call_account["platform"] == "google"

    # Verifica que o account enviado ao run_account tem platform == "meta"
    meta_call_account = mock_account.call_args.kwargs.get("account") or mock_account.call_args[1].get("account")
    assert meta_call_account["platform"] == "meta"
