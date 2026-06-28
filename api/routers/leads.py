"""Consulta de leads para o attribution loop CRM → campanha."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException

from agent.config import settings
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)
router = APIRouter(tags=["leads"])


def verify_api_key(api_key: str) -> None:
    """Valida a chave interna usada por automações n8n."""
    if api_key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


@router.get("/leads")
async def get_lead_by_crm_id(
    crm_deal_id: str,
    api_key: str = Header(..., alias="X-API-Key"),
) -> dict[str, Any]:
    """Retorna o lead vinculado ao deal do CRM, ou objeto vazio se não existir."""
    verify_api_key(api_key)
    try:
        result = (
            supabase.table("leads")
            .select("*")
            .eq("crm_deal_id", crm_deal_id)
            .execute()
        )
    except Exception as exc:
        log.error("leads.lookup_failed", crm_deal_id=crm_deal_id, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Database query failed: {exc}") from exc
    return result.data[0] if result.data else {}
