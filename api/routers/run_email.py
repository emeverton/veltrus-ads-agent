"""api/routers/run_email.py — Dispara o Agente de Email Marketing em background."""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.email_graph import compiled_email_graph
from agent.tools.supabase_client import supabase
from api.routers.decisions import _require_api_key

log = structlog.get_logger(__name__)
router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunEmailRequest(BaseModel):
    client_id: str = Field(..., description="UUID do cliente em public.clients")
    list_id: int = Field(..., description="ID da lista de contatos no Brevo")
    context: str = Field("", description="Contexto adicional para o PESQUISADOR/COPYWRITER")


def _run_graph_in_thread(initial_state: dict[str, Any]) -> None:
    """Roda o grafo em uma thread separada com seu próprio event loop."""
    try:
        asyncio.run(compiled_email_graph.ainvoke(initial_state))
        log.info(
            "run_email.graph_done",
            client_id=initial_state.get("client", {}).get("id"),
        )
    except Exception as exc:
        log.error(
            "run_email.graph_failed",
            client_id=initial_state.get("client", {}).get("id"),
            error=str(exc),
        )


@router.post("")
async def trigger_email_run(
    body: RunEmailRequest,
    _key: str = Depends(_require_api_key),
) -> dict[str, str]:
    """Dispara compiled_email_graph em background para um cliente."""
    log.info(
        "run_email.triggered",
        client_id=body.client_id,
        list_id=body.list_id,
    )

    try:
        result = (
            supabase.table("clients")
            .select("*")
            .eq("id", body.client_id)
            .single()
            .execute()
        )
    except Exception as exc:
        log.error("run_email.client_lookup_failed", client_id=body.client_id, error=str(exc))
        raise HTTPException(status_code=404, detail=f"client {body.client_id} not found") from exc

    client = result.data
    if not client:
        raise HTTPException(status_code=404, detail=f"client {body.client_id} not found")

    business_dna = dict(client.get("business_dna") or {})
    if body.context:
        business_dna["run_context"] = body.context
        business_dna["preferred_list_id"] = body.list_id
    client["business_dna"] = business_dna

    initial_state: dict[str, Any] = {
        "client": client,
        "briefing": {},
        "analysis": {"list_id": body.list_id},
        "copy_variants": [],
        "html_content": "",
        "scheduled_at": "",
        "campaign_id": None,
        "db_row_id": None,
        "report": {},
    }

    thread = threading.Thread(
        target=_run_graph_in_thread,
        args=(initial_state,),
        daemon=True,
        name=f"email-graph-{body.client_id}",
    )
    thread.start()

    return {
        "status": "started",
        "client_id": body.client_id,
        "timestamp": _now_iso(),
    }
