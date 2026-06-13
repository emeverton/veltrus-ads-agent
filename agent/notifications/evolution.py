"""Notificações de aprovação humana via Evolution API (WhatsApp)."""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from agent.config import settings

log = structlog.get_logger(__name__)

_DEFAULT_INSTANCE = "veltrus-agent"


def _normalize_phone(number: str) -> str:
    """Remove caracteres não numéricos; Evolution espera E.164 sem '+'."""
    return "".join(ch for ch in number if ch.isdigit())


def _build_approval_message(
    *,
    campaign_name: str,
    action_type: str,
    risk_level: str,
    reasoning: str,
    decision_id: str,
    api_base_url: str,
) -> str:
    api_base = api_base_url.rstrip("/")
    return (
        f"🤖 *Veltrus Ads Agent*\n\n"
        f"*Campanha:* {campaign_name}\n"
        f"*Ação:* {action_type}\n"
        f"*Risco:* {risk_level}\n\n"
        f"_{reasoning}_\n\n"
        f"ID: `{decision_id}`\n\n"
        f"Para aprovar via API:\n"
        f"`PATCH {api_base}/decisions/{decision_id}/approve`\n"
        f"Header: `X-API-Key: <sua-chave>`\n\n"
        f"Para rejeitar:\n"
        f"`PATCH {api_base}/decisions/{decision_id}/reject`"
    )


async def fetch_active_instance_name() -> str | None:
    """Retorna o nome da primeira instância com connectionStatus=open."""
    if not settings.evolution_api_key or not settings.evolution_api_base_url:
        return None

    url = f"{settings.evolution_api_base_url.rstrip('/')}/instance/fetchInstances"
    headers = {"apikey": settings.evolution_api_key}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            instances: list[dict[str, Any]] = resp.json()
    except Exception as exc:
        log.error("evolution.fetch_instances_failed", error=str(exc))
        return None

    for inst in instances:
        if inst.get("connectionStatus") == "open" and inst.get("name"):
            return str(inst["name"])

    return None


async def send_text_message(*, number: str, text: str, instance_name: str | None = None) -> dict[str, Any]:
    """Envia mensagem de texto via Evolution API POST /message/sendText/{instance}."""
    api_key = settings.evolution_api_key
    base_url = settings.evolution_api_base_url.rstrip("/")

    if not api_key or not base_url:
        raise RuntimeError("EVOLUTION_API_KEY e EVOLUTION_API_BASE_URL são obrigatórios")

    instance = instance_name or settings.evolution_instance_name
    if not instance:
        instance = await fetch_active_instance_name()
    if not instance:
        instance = _DEFAULT_INSTANCE

    phone = _normalize_phone(number)
    if not phone:
        raise ValueError("Número de destino inválido")

    url = f"{base_url}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": phone, "text": text}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()

    log.info(
        "evolution.message_sent",
        instance=instance,
        number=phone,
        message_id=(body.get("key") or {}).get("id"),
    )
    return {"instance": instance, "response": body, "http_status": resp.status_code}


async def send_approval_request(
    *,
    campaign_name: str,
    action_type: str,
    risk_level: str,
    reasoning: str,
    decision_id: str,
    phone_number: str | None = None,
) -> dict[str, Any]:
    """Envia solicitação de aprovação humana via Evolution API."""
    phone = phone_number or settings.notify_phone_number
    if not phone:
        return {
            "notification_sent": False,
            "channel": "log_only",
            "message": (
                f"[{risk_level}] Campanha '{campaign_name}': "
                f"ação '{action_type}' aguarda aprovação. ID: {decision_id}"
            ),
        }

    if not settings.evolution_api_key or not settings.evolution_api_base_url:
        log.warning("evolution.not_configured", decision_id=decision_id)
        return {
            "notification_sent": False,
            "channel": "log_only",
            "message": (
                f"[{risk_level}] Campanha '{campaign_name}': "
                f"ação '{action_type}' aguarda aprovação. ID: {decision_id} "
                "(Evolution API não configurada)"
            ),
        }

    api_public_url = settings.api_public_url or f"http://localhost:{settings.api_port}"
    text = _build_approval_message(
        campaign_name=campaign_name,
        action_type=action_type,
        risk_level=risk_level,
        reasoning=reasoning,
        decision_id=decision_id,
        api_base_url=api_public_url,
    )

    try:
        result = await send_text_message(number=phone, text=text)
        return {
            "notification_sent": True,
            "channel": "evolution_api",
            "instance": result["instance"],
            "http_status": result["http_status"],
        }
    except Exception as exc:
        log.error("evolution.send_failed", decision_id=decision_id, error=str(exc))
        return {
            "notification_sent": False,
            "channel": "evolution_api",
            "error": str(exc),
        }
