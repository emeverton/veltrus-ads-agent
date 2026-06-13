"""
Ponto de entrada do agente com APScheduler.

Uso:
    python -m agent.main

Agenda run_all_accounts() com o intervalo definido em AGENT_CYCLE_INTERVAL_MINUTES.
Executa um ciclo imediatamente ao iniciar, depois repete no intervalo configurado.
"""
from __future__ import annotations

import asyncio
import signal

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import settings
from agent.run import run_all_accounts

log = structlog.get_logger(__name__)


async def main() -> None:
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        run_all_accounts,
        trigger=IntervalTrigger(minutes=settings.agent_cycle_interval_minutes),
        id="agent_cycle",
        name="Veltrus Ads Agent Cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    log.info(
        "agent.scheduler.started",
        interval_minutes=settings.agent_cycle_interval_minutes,
        autonomous_mode=settings.agent_autonomous_mode,
    )

    # Executa um ciclo imediatamente ao iniciar sem esperar o primeiro intervalo
    log.info("agent.scheduler.initial_run")
    try:
        await run_all_accounts()
    except Exception:
        log.exception("agent.scheduler.initial_run.error")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("agent.scheduler.stopping", signal=sig)
        scheduler.shutdown(wait=False)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    await stop_event.wait()
    log.info("agent.scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(main())
