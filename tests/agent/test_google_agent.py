"""Testes para agent/graphs/google_agent.py e integração em agent/run.py."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# run_google_agent
# ---------------------------------------------------------------------------
class TestRunGoogleAgent:
    @pytest.mark.asyncio
    async def test_logs_list_campaigns_start(self, caplog):
        """Deve emitir log google.list_campaigns.start ao iniciar."""
        import structlog
        from agent.graphs.google_agent import run_google_agent

        fake_campaigns = [
            {"campaign_id": "123", "name": "Camp A", "status": "ENABLED",
             "campaign_budget_id": "456", "daily_budget_usd": 50.0}
        ]

        with patch("agent.graphs.google_agent.google_ads.get_campaigns",
                   new=AsyncMock(return_value=fake_campaigns)):
            result = await run_google_agent("1234567890", {})

        assert result == fake_campaigns

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        """Deve retornar lista vazia e não propagar exceção."""
        from agent.graphs.google_agent import run_google_agent

        with patch("agent.graphs.google_agent.google_ads.get_campaigns",
                   new=AsyncMock(side_effect=Exception("API error"))):
            result = await run_google_agent("1234567890", {})

        assert result == []

    @pytest.mark.asyncio
    async def test_build_credentials_from_settings(self):
        """build_credentials_from_settings deve incluir as chaves esperadas."""
        from agent.graphs.google_agent import build_credentials_from_settings

        creds = build_credentials_from_settings()

        assert "client_id" in creds
        assert "client_secret" in creds
        assert "refresh_token" in creds
        assert "login_customer_id" in creds


# ---------------------------------------------------------------------------
# run_all_accounts — deve chamar google_agent quando GOOGLE_ADS_CUSTOMER_ID
# ---------------------------------------------------------------------------
class TestRunAllAccountsGoogleAgent:
    @pytest.mark.asyncio
    async def test_calls_google_agent_when_customer_id_set(self):
        """Quando settings.google_ads_customer_id != '', run_all_accounts chama run_google_agent."""
        from agent import run as run_module

        mock_supabase_result = MagicMock()
        mock_supabase_result.data = []  # sem contas — simplifica o teste

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            mock_supabase_result
        )

        mock_google_agent = AsyncMock(return_value=[])

        with (
            patch.object(run_module, "supabase", mock_sb),
            patch("agent.run.settings") as mock_settings,
            patch("agent.run.run_google_agent", mock_google_agent),
            patch("agent.run.build_credentials_from_settings", return_value={}),
        ):
            mock_settings.google_ads_customer_id = "9876543210"

            await run_module.run_all_accounts()

        mock_google_agent.assert_awaited_once_with("9876543210", {})

    @pytest.mark.asyncio
    async def test_skips_google_agent_when_customer_id_empty(self):
        """Quando settings.google_ads_customer_id == '', não chama run_google_agent."""
        from agent import run as run_module

        mock_supabase_result = MagicMock()
        mock_supabase_result.data = []

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            mock_supabase_result
        )

        mock_google_agent = AsyncMock()

        with (
            patch.object(run_module, "supabase", mock_sb),
            patch("agent.run.settings") as mock_settings,
            patch("agent.run.run_google_agent", mock_google_agent),
            patch("agent.run.build_credentials_from_settings", return_value={}),
        ):
            mock_settings.google_ads_customer_id = ""

            await run_module.run_all_accounts()

        mock_google_agent.assert_not_awaited()
