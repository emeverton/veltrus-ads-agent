"""Celery application — broker Redis, agendamento via beat."""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import timedelta

_redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_interval_minutes = int(os.environ.get("AGENT_CYCLE_INTERVAL_MINUTES", "30"))

app = Celery(
    "veltrus",
    broker=_redis_url,
    backend=_redis_url,
    include=["tasks"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

app.conf.beat_schedule = {
    "run-agent-cycle": {
        "task": "tasks.run_agent_cycle",
        "schedule": timedelta(minutes=_interval_minutes),
        "options": {"expires": _interval_minutes * 60 - 30},
    },
}
