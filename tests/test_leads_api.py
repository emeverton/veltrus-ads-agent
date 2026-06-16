"""Testes do endpoint de leads usado pelo n8n attribution loop."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.routers import leads


@pytest.mark.asyncio
async def test_get_lead_by_crm_id_returns_first_match(mocker):
    mocker.patch.object(leads.settings, "api_secret_key", "secret")
    fake_supabase = mocker.patch.object(leads, "supabase")
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value
    ).data = [{"id": "lead-1", "crm_deal_id": "deal-123"}]

    result = await leads.get_lead_by_crm_id("deal-123", api_key="secret")

    fake_supabase.table.assert_called_once_with("leads")
    assert result == {"id": "lead-1", "crm_deal_id": "deal-123"}


@pytest.mark.asyncio
async def test_get_lead_by_crm_id_blocks_invalid_api_key(mocker):
    mocker.patch.object(leads.settings, "api_secret_key", "secret")
    fake_supabase = mocker.patch.object(leads, "supabase")

    with pytest.raises(HTTPException) as exc:
        await leads.get_lead_by_crm_id("deal-123", api_key="wrong")

    assert exc.value.status_code == 403
    fake_supabase.table.assert_not_called()
