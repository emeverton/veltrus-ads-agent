"""api/routers/leads.py — Consulta de leads para o attribution loop (n8n / Kommo)."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends

from agent.tools.supabase_client import supabase
from api.routers.decisions import _require_api_key

log = structlog.get_logger(__name__)
router = APIRouter(tags=["leads"])


@router.get("/leads")
async def get_lead_by_crm_id(
    crm_deal_id: str,
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Busca lead pelo crm_deal_id para o webhook Kommo → attribution loop."""
    result = (
        supabase.table("leads")
        .select("*")
        .eq("crm_deal_id", crm_deal_id)
        .execute()
    )
    rows = result.data or []
    if not rows:
        log.info("leads.not_found", crm_deal_id=crm_deal_id)
        return {}
    log.info("leads.found", crm_deal_id=crm_deal_id, lead_id=rows[0].get("id"))
    return rows[0]
