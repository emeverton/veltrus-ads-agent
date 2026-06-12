"""Tarefas Celery — ciclos do agente e kill switch."""
from __future__ import annotations

import asyncio

import structlog

from agent.celery_app import celery_app
from agent.run import run_all_accounts

log = structlog.get_logger(__name__)


@celery_app.task(name="agent.tasks.run_agent_cycle", bind=True, max_retries=2)
def run_agent_cycle(self) -> dict[str, str]:
    """Executa um ciclo completo do grafo LangGraph para todas as contas ativas."""
    log.info("celery.agent_cycle.start", task_id=self.request.id)
    try:
        asyncio.run(run_all_accounts())
    except Exception as exc:
        log.exception("celery.agent_cycle.error", task_id=self.request.id)
        raise self.retry(exc=exc, countdown=60) from exc

    log.info("celery.agent_cycle.done", task_id=self.request.id)
    return {"status": "completed", "task_id": self.request.id}


@celery_app.task(name="agent.tasks.run_kill_switch", bind=True, max_retries=1)
def run_kill_switch(self) -> dict[str, str]:
    """Executa o kill switch financeiro (independente do grafo LangGraph)."""
    from scripts.kill_switch import main as kill_switch_main

    log.info("celery.kill_switch.start", task_id=self.request.id)
    try:
        exit_code = asyncio.run(kill_switch_main(dry_run=False))
    except Exception as exc:
        log.exception("celery.kill_switch.error", task_id=self.request.id)
        raise self.retry(exc=exc, countdown=120) from exc

    status = "completed" if exit_code == 0 else "completed_with_errors"
    log.info("celery.kill_switch.done", task_id=self.request.id, exit_code=exit_code)
    return {"status": status, "exit_code": str(exit_code), "task_id": self.request.id}
