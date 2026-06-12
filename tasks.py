"""Celery tasks do Veltrus Ads Agent."""
from __future__ import annotations

import asyncio

import structlog

from celery_app import app

log = structlog.get_logger(__name__)


@app.task(name="tasks.run_agent_cycle", bind=True, max_retries=3, default_retry_delay=60)
def run_agent_cycle(self) -> dict:  # type: ignore[override]
    """Executa um ciclo completo do agente para todas as contas ativas."""
    log.info("task.run_agent_cycle.start", task_id=self.request.id)
    try:
        from agent.run import run_all_accounts  # import tardio evita circular

        asyncio.run(run_all_accounts())
        log.info("task.run_agent_cycle.done", task_id=self.request.id)
        return {"status": "ok"}
    except Exception as exc:
        log.exception("task.run_agent_cycle.error", task_id=self.request.id)
        raise self.retry(exc=exc) from exc
