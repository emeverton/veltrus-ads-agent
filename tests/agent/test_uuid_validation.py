"""Testes para validação de UUID no nó estrategista e na ferramenta save_decision."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.graph import is_valid_uuid, estrategista_node, save_decision


# ---------------------------------------------------------------------------
# is_valid_uuid
# ---------------------------------------------------------------------------
class TestIsValidUuid:
    def test_valid_uuid4(self):
        assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uuid_any_version(self):
        assert is_valid_uuid("12345678-1234-5678-1234-567812345678") is True

    def test_na_string(self):
        assert is_valid_uuid("n/a") is False

    def test_empty_string(self):
        assert is_valid_uuid("") is False

    def test_arbitrary_text(self):
        assert is_valid_uuid("not-a-uuid") is False

    def test_none_value(self):
        assert is_valid_uuid(None) is False

    def test_integer(self):
        assert is_valid_uuid(12345) is False


# ---------------------------------------------------------------------------
# estrategista_node — deve logar warning e retornar monitor_only para UUID inválido
# ---------------------------------------------------------------------------
class TestEstrategistaNodeUuidValidation:
    @pytest.mark.asyncio
    async def test_skip_on_invalid_uuid(self):
        """Quando LLM retorna campaign_uuid='n/a', estrategista deve retornar monitor_only."""
        llm_json_response = (
            '{"campaign_uuid": "n/a", "campaign_id": "ext123", '
            '"campaign_name": "Test", "platform": "meta", '
            '"action_type": "budget_decrease", "params": {}, '
            '"reasoning": "CPA alto"}'
        )

        state = {
            "anomalies": [{"campaign_uuid": "n/a", "campaign_id": "ext123"}],
            "client": {"name": "Test Client", "vertical": "ecommerce", "business_dna": {}},
        }

        with patch("agent.graph._agent_loop", new=AsyncMock(return_value=llm_json_response)):
            result = await estrategista_node(state)

        decision = result["decision"]
        assert decision["action_type"] == "monitor_only"
        assert decision["campaign_uuid"] == ""

    @pytest.mark.asyncio
    async def test_passes_on_valid_uuid(self):
        """Quando LLM retorna UUID válido, estrategista deve preservar a decisão."""
        valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        llm_json_response = (
            f'{{"campaign_uuid": "{valid_uuid}", "campaign_id": "ext123", '
            f'"campaign_name": "Test", "platform": "meta", '
            f'"action_type": "budget_decrease", "params": {{}}, '
            f'"reasoning": "CPA alto"}}'
        )

        state = {
            "anomalies": [{"campaign_uuid": valid_uuid, "campaign_id": "ext123"}],
            "client": {"name": "Test Client", "vertical": "ecommerce", "business_dna": {}},
        }

        with patch("agent.graph._agent_loop", new=AsyncMock(return_value=llm_json_response)):
            result = await estrategista_node(state)

        decision = result["decision"]
        assert decision["action_type"] == "budget_decrease"
        assert decision["campaign_uuid"] == valid_uuid


# ---------------------------------------------------------------------------
# save_decision — deve pular INSERT para UUID inválido
# ---------------------------------------------------------------------------
class TestSaveDecisionUuidValidation:
    @pytest.mark.asyncio
    async def test_skip_invalid_uuid(self):
        result = await save_decision.ainvoke({
            "campaign_uuid": "n/a",
            "action_type": "pause_campaign",
            "reasoning": "teste",
            "payload": {},
            "executed": False,
        })
        assert result.get("skipped") is True
        assert result.get("reason") == "invalid_uuid"

    @pytest.mark.asyncio
    async def test_insert_valid_uuid(self):
        valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": valid_uuid, "action_type": "pause_campaign"}
        ]

        with patch("agent.graph.supabase", mock_sb):
            result = await save_decision.ainvoke({
                "campaign_uuid": valid_uuid,
                "action_type": "pause_campaign",
                "reasoning": "teste",
                "payload": {},
                "executed": False,
            })

        assert result.get("id") == valid_uuid
        mock_sb.table.assert_called_with("agent_decisions")
