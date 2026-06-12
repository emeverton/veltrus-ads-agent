"""Celery — fila de tarefas do Veltrus Ads Agent."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from agent.config import settings

celery_app = Celery(
    "veltrus_ads_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["agent.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "agent.tasks.run_agent_cycle": {"queue": "agent"},
        "agent.tasks.run_kill_switch": {"queue": "agent"},
    },
)

_interval_seconds = float(max(settings.agent_cycle_interval_minutes, 5) * 60)

celery_app.conf.beat_schedule = {
    "agent-cycle": {
        "task": "agent.tasks.run_agent_cycle",
        "schedule": _interval_seconds,
    },
    "kill-switch-hourly": {
        "task": "agent.tasks.run_kill_switch",
        "schedule": crontab(minute=0),
    },
}
