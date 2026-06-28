"""
api/routers/leads.py — Consulta de leads por CRM deal ID

GET /leads?crm_deal_id=<id>   retorna o lead correspondente (usado pelo n8n Attribution Loop)
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.security.api_key import APIKeyHeader
from fastapi import Security

from agent.config import settings
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/leads", tags=["leads"])

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def _verify_api_key(key: str = Security(_api_key_header)) -> str:
    if key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


@router.get("")
async def get_lead_by_crm_id(
    crm_deal_id: str,
    _key: str = Security(_verify_api_key),
) -> dict[str, Any]:
    """Retorna o lead vinculado a um deal do CRM (usado pelo n8n Attribution Loop)."""
    if not crm_deal_id:
        raise HTTPException(status_code=422, detail="crm_deal_id is required")

    log.info("leads.get_by_crm_id", crm_deal_id=crm_deal_id)

    try:
        result = (
            supabase.table("leads")
            .select("*")
            .eq("crm_deal_id", crm_deal_id)
            .execute()
        )
    except Exception as exc:
        log.error("leads.query_failed", crm_deal_id=crm_deal_id, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Database query failed: {exc}") from exc

    if not result.data:
        log.info("leads.not_found", crm_deal_id=crm_deal_id)
        return {}

    return result.data[0]
