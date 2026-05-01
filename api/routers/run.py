"""api/routers/run.py — Dispara um ciclo completo do agente em background."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends

from agent.run import run_all_accounts
from api.routers.decisions import _require_api_key

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/run", tags=["agent"])


def _run_in_background() -> None:
    """Wrapper síncrono para o BackgroundTasks do FastAPI.

    BackgroundTasks cria uma nova thread; asyncio.run() abre um loop nela,
    independente do loop da request.
    """
    asyncio.run(run_all_accounts())


@router.post("")
async def trigger_run(
    background_tasks: BackgroundTasks,
    _key: str = Depends(_require_api_key),
) -> dict[str, str]:
    """Dispara run_all_accounts() em background e retorna imediatamente."""
    background_tasks.add_task(_run_in_background)
    log.info("run.triggered_via_api")
    return {
        "status": "started",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
