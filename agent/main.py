"""Ponto de entrada do agente — agendamento periódico via APScheduler."""
from __future__ import annotations

import asyncio
import signal
import sys

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import settings
from agent.run import run_all_accounts

log = structlog.get_logger(__name__)


def _run_cycle() -> None:
    log.info("scheduler.cycle.triggered")
    try:
        asyncio.run(run_all_accounts())
    except Exception:
        log.exception("scheduler.cycle.error")


def main() -> None:
    interval = settings.agent_cycle_interval_minutes
    log.info("scheduler.start", interval_minutes=interval)

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        _run_cycle,
        trigger=IntervalTrigger(minutes=interval),
        id="run_agent_cycle",
        name="Veltrus agent cycle",
        max_instances=1,
        coalesce=True,
    )

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("scheduler.shutdown", signal=signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _run_cycle()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler.stopped")


if __name__ == "__main__":
    main()
