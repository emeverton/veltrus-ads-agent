"""Ferramentas Email Marketing via Brevo API v3 (HTTP direto)."""
from __future__ import annotations

import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
import structlog

from agent.config import settings

log = structlog.get_logger(__name__)

_BASE_URL = settings.brevo_api_base_url.rstrip("/")

# ---------------------------------------------------------------------------
# Retry com backoff exponencial para rate-limit / 5xx
# ---------------------------------------------------------------------------
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # segundos
_DEFAULT_TIMEOUT = 30  # segundos


def _headers() -> dict[str, str]:
    if not settings.brevo_api_key:
        raise RuntimeError("BREVO_API_KEY não configurado em settings/.env")
    return {
        "api-key": settings.brevo_api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> Any:
    """Executa request HTTP com retry exponencial em rate-limit / 5xx."""
    url = f"{_BASE_URL}{path}"

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=_headers(),
                params=params,
                json=json,
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                log.warning(
                    "brevo.network_error",
                    method=method,
                    path=path,
                    attempt=attempt,
                    error=str(exc),
                    retry_in_seconds=wait,
                )
                time.sleep(wait)
                continue
            raise

        if resp.status_code in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES:
            wait = _BACKOFF_BASE ** attempt
            log.warning(
                "brevo.rate_limit",
                method=method,
                path=path,
                status_code=resp.status_code,
                attempt=attempt,
                retry_in_seconds=wait,
            )
            time.sleep(wait)
            continue

        if not resp.ok:
            log.error(
                "brevo.http_error",
                method=method,
                path=path,
                status_code=resp.status_code,
                body=resp.text[:500],
            )
            resp.raise_for_status()

        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# 1. get_account_stats
# ---------------------------------------------------------------------------
async def get_account_stats(days: int = 30) -> dict[str, Any]:
    """Retorna métricas agregadas da conta nos últimos *days* dias.

    Agrega métricas de todas as campanhas de email enviadas no período.
    """
    log.info("brevo.get_account_stats.start", days=days)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    account = _request("GET", "/account")

    campaigns_payload = _request(
        "GET",
        "/emailCampaigns",
        params={
            "status": "sent",
            "startDate": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "endDate": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "limit": 100,
            "offset": 0,
        },
    )
    campaigns = campaigns_payload.get("campaigns") or []

    totals = {
        "sent": 0,
        "delivered": 0,
        "opens": 0,
        "unique_opens": 0,
        "clicks": 0,
        "unique_clicks": 0,
        "hard_bounces": 0,
        "soft_bounces": 0,
        "complaints": 0,
        "unsubscriptions": 0,
    }

    for c in campaigns:
        s = c.get("statistics", {}).get("globalStats", {}) or {}
        totals["sent"] += int(s.get("sent") or 0)
        totals["delivered"] += int(s.get("delivered") or 0)
        totals["opens"] += int(s.get("viewed") or 0)
        totals["unique_opens"] += int(s.get("uniqueViews") or 0)
        totals["clicks"] += int(s.get("clickers") or 0)
        totals["unique_clicks"] += int(s.get("uniqueClicks") or 0)
        totals["hard_bounces"] += int(s.get("hardBounces") or 0)
        totals["soft_bounces"] += int(s.get("softBounces") or 0)
        totals["complaints"] += int(s.get("complaints") or 0)
        totals["unsubscriptions"] += int(s.get("unsubscriptions") or 0)

    delivered = totals["delivered"]
    open_rate = (totals["unique_opens"] / delivered) if delivered else 0.0
    click_rate = (totals["unique_clicks"] / delivered) if delivered else 0.0
    bounce_rate = ((totals["hard_bounces"] + totals["soft_bounces"]) / totals["sent"]) if totals["sent"] else 0.0

    stats = {
        "period_days": days,
        "date_start": start.date().isoformat(),
        "date_end": end.date().isoformat(),
        "campaigns_sent": len(campaigns),
        "totals": totals,
        "open_rate": round(open_rate, 6),
        "click_rate": round(click_rate, 6),
        "bounce_rate": round(bounce_rate, 6),
        "plan": account.get("plan", []),
        "email_credits": account.get("plan", [{}])[0].get("credits") if account.get("plan") else None,
    }

    log.info(
        "brevo.get_account_stats.done",
        days=days,
        campaigns_sent=stats["campaigns_sent"],
        open_rate=stats["open_rate"],
        click_rate=stats["click_rate"],
    )
    return stats


# ---------------------------------------------------------------------------
# 2. get_lists
# ---------------------------------------------------------------------------
async def get_lists() -> list[dict[str, Any]]:
    """Lista todas as listas de contatos da conta."""
    log.info("brevo.get_lists.start")

    lists: list[dict[str, Any]] = []
    offset = 0
    limit = 50

    while True:
        payload = _request(
            "GET",
            "/contacts/lists",
            params={"limit": limit, "offset": offset},
        )
        batch = payload.get("lists") or []
        for raw in batch:
            lists.append({
                "list_id": raw.get("id"),
                "name": raw.get("name", ""),
                "folder_id": raw.get("folderId"),
                "total_subscribers": int(raw.get("totalSubscribers") or 0),
                "total_blacklisted": int(raw.get("totalBlacklisted") or 0),
                "unique_subscribers": int(raw.get("uniqueSubscribers") or 0),
                "created_at": raw.get("createdAt"),
                "dynamic_list": bool(raw.get("dynamicList") or False),
            })
        if len(batch) < limit:
            break
        offset += limit

    log.info("brevo.get_lists.done", total=len(lists))
    return lists


# ---------------------------------------------------------------------------
# 3. get_campaigns
# ---------------------------------------------------------------------------
async def get_campaigns(limit: int = 10) -> list[dict[str, Any]]:
    """Retorna as últimas *limit* campanhas com métricas globais."""
    log.info("brevo.get_campaigns.start", limit=limit)

    payload = _request(
        "GET",
        "/emailCampaigns",
        params={"limit": limit, "offset": 0, "sort": "desc"},
    )
    raw_campaigns = payload.get("campaigns") or []

    campaigns: list[dict[str, Any]] = []
    for raw in raw_campaigns:
        stats = (raw.get("statistics") or {}).get("globalStats") or {}
        sent = int(stats.get("sent") or 0)
        delivered = int(stats.get("delivered") or 0)
        unique_opens = int(stats.get("uniqueViews") or 0)
        unique_clicks = int(stats.get("uniqueClicks") or 0)

        campaigns.append({
            "campaign_id": raw.get("id"),
            "name": raw.get("name", ""),
            "subject": raw.get("subject", ""),
            "status": raw.get("status", ""),
            "type": raw.get("type", ""),
            "scheduled_at": raw.get("scheduledAt"),
            "sent_date": raw.get("sentDate"),
            "sent": sent,
            "delivered": delivered,
            "unique_opens": unique_opens,
            "unique_clicks": unique_clicks,
            "hard_bounces": int(stats.get("hardBounces") or 0),
            "soft_bounces": int(stats.get("softBounces") or 0),
            "unsubscriptions": int(stats.get("unsubscriptions") or 0),
            "complaints": int(stats.get("complaints") or 0),
            "open_rate": round(unique_opens / delivered, 6) if delivered else 0.0,
            "click_rate": round(unique_clicks / delivered, 6) if delivered else 0.0,
        })

    log.info("brevo.get_campaigns.done", total=len(campaigns))
    return campaigns


# ---------------------------------------------------------------------------
# 4. create_email_campaign
# ---------------------------------------------------------------------------
async def create_email_campaign(
    name: str,
    subject: str,
    html_content: str,
    list_id: int,
    scheduled_at: datetime | str | None = None,
    sender_name: str | None = None,
    sender_email: str | None = None,
) -> dict[str, Any]:
    """Cria uma campanha de email.

    Se *scheduled_at* for fornecido, a campanha é agendada — caso contrário,
    fica como rascunho até `send_campaign` ser chamado.
    """
    log.info(
        "brevo.create_email_campaign.start",
        name=name,
        list_id=list_id,
        scheduled_at=str(scheduled_at) if scheduled_at else None,
    )

    sender: dict[str, Any] = {}
    if sender_name:
        sender["name"] = sender_name
    if sender_email:
        sender["email"] = sender_email

    body: dict[str, Any] = {
        "name": name,
        "subject": subject,
        "htmlContent": html_content,
        "recipients": {"listIds": [int(list_id)]},
    }
    if sender:
        body["sender"] = sender

    if scheduled_at is not None:
        if isinstance(scheduled_at, datetime):
            iso = scheduled_at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        else:
            iso = scheduled_at
        body["scheduledAt"] = iso

    result = _request("POST", "/emailCampaigns", json=body)
    campaign_id = result.get("id")

    log.info(
        "brevo.create_email_campaign.done",
        campaign_id=campaign_id,
        name=name,
        list_id=list_id,
    )
    return {
        "campaign_id": campaign_id,
        "name": name,
        "subject": subject,
        "list_id": int(list_id),
        "scheduled_at": body.get("scheduledAt"),
    }


# ---------------------------------------------------------------------------
# 5. send_campaign
# ---------------------------------------------------------------------------
async def send_campaign(campaign_id: int) -> dict[str, Any]:
    """Dispara imediatamente uma campanha em rascunho."""
    log.info("brevo.send_campaign.start", campaign_id=campaign_id)

    _request("POST", f"/emailCampaigns/{int(campaign_id)}/sendNow")

    log.info("brevo.send_campaign.done", campaign_id=campaign_id)
    return {"campaign_id": int(campaign_id), "status": "sent"}


# ---------------------------------------------------------------------------
# 6. get_campaign_report
# ---------------------------------------------------------------------------
async def get_campaign_report(campaign_id: int) -> dict[str, Any]:
    """Retorna métricas pós-disparo de uma campanha."""
    log.info("brevo.get_campaign_report.start", campaign_id=campaign_id)

    raw = _request("GET", f"/emailCampaigns/{int(campaign_id)}")
    stats = (raw.get("statistics") or {}).get("globalStats") or {}

    sent = int(stats.get("sent") or 0)
    delivered = int(stats.get("delivered") or 0)
    unique_opens = int(stats.get("uniqueViews") or 0)
    unique_clicks = int(stats.get("uniqueClicks") or 0)
    hard_bounces = int(stats.get("hardBounces") or 0)
    soft_bounces = int(stats.get("softBounces") or 0)
    unsubscriptions = int(stats.get("unsubscriptions") or 0)
    complaints = int(stats.get("complaints") or 0)

    open_rate = (unique_opens / delivered) if delivered else 0.0
    click_rate = (unique_clicks / delivered) if delivered else 0.0
    ctor = (unique_clicks / unique_opens) if unique_opens else 0.0
    bounce_rate = ((hard_bounces + soft_bounces) / sent) if sent else 0.0
    unsubscribe_rate = (unsubscriptions / delivered) if delivered else 0.0

    report = {
        "campaign_id": int(campaign_id),
        "name": raw.get("name", ""),
        "subject": raw.get("subject", ""),
        "status": raw.get("status", ""),
        "sent_date": raw.get("sentDate"),
        "sent": sent,
        "delivered": delivered,
        "unique_opens": unique_opens,
        "opens": int(stats.get("viewed") or 0),
        "unique_clicks": unique_clicks,
        "clicks": int(stats.get("clickers") or 0),
        "hard_bounces": hard_bounces,
        "soft_bounces": soft_bounces,
        "unsubscriptions": unsubscriptions,
        "complaints": complaints,
        "open_rate": round(open_rate, 6),
        "click_rate": round(click_rate, 6),
        "ctor": round(ctor, 6),
        "bounce_rate": round(bounce_rate, 6),
        "unsubscribe_rate": round(unsubscribe_rate, 6),
        "raw_payload": raw,
    }

    log.info(
        "brevo.get_campaign_report.done",
        campaign_id=campaign_id,
        delivered=delivered,
        open_rate=report["open_rate"],
        click_rate=report["click_rate"],
    )
    return report


# ---------------------------------------------------------------------------
# 7. add_contact
# ---------------------------------------------------------------------------
async def add_contact(
    email: str,
    name: str | None = None,
    list_id: int | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adiciona (ou atualiza) um contato. Se *list_id* for passado, inscreve na lista."""
    log.info("brevo.add_contact.start", email=email, list_id=list_id)

    attrs: dict[str, Any] = dict(attributes or {})
    if name and "FIRSTNAME" not in attrs and "NAME" not in attrs:
        parts = name.strip().split(maxsplit=1)
        attrs["FIRSTNAME"] = parts[0]
        if len(parts) > 1:
            attrs["LASTNAME"] = parts[1]

    body: dict[str, Any] = {
        "email": email,
        "updateEnabled": True,
    }
    if attrs:
        body["attributes"] = attrs
    if list_id is not None:
        body["listIds"] = [int(list_id)]

    result = _request("POST", "/contacts", json=body)
    contact_id = result.get("id")

    log.info(
        "brevo.add_contact.done",
        email=email,
        contact_id=contact_id,
        list_id=list_id,
    )
    return {
        "email": email,
        "contact_id": contact_id,
        "list_id": int(list_id) if list_id is not None else None,
        "attributes": attrs,
    }


# ---------------------------------------------------------------------------
# 8. get_best_send_time
# ---------------------------------------------------------------------------
async def get_best_send_time(list_id: int) -> dict[str, Any]:
    """Analisa campanhas passadas que atingiram a *list_id* e infere o melhor horário.

    Heurística: agrupa por (weekday, hour) o `uniqueViews / delivered` ponderado
    pelo volume entregue, e retorna o slot de maior open rate.
    """
    log.info("brevo.get_best_send_time.start", list_id=list_id)

    payload = _request(
        "GET",
        "/emailCampaigns",
        params={"status": "sent", "limit": 100, "offset": 0, "sort": "desc"},
    )
    raw_campaigns = payload.get("campaigns") or []

    target = int(list_id)
    samples: list[tuple[int, int, float, int]] = []  # (weekday, hour, open_rate, delivered)

    for c in raw_campaigns:
        recipients = c.get("recipients") or {}
        list_ids = recipients.get("listIds") or []
        if target not in list_ids:
            continue

        sent_date = c.get("sentDate")
        if not sent_date:
            continue
        try:
            dt = datetime.fromisoformat(sent_date.replace("Z", "+00:00"))
        except ValueError:
            continue

        stats = (c.get("statistics") or {}).get("globalStats") or {}
        delivered = int(stats.get("delivered") or 0)
        unique_opens = int(stats.get("uniqueViews") or 0)
        if delivered <= 0:
            continue

        open_rate = unique_opens / delivered
        samples.append((dt.weekday(), dt.hour, open_rate, delivered))

    if not samples:
        log.warning("brevo.get_best_send_time.no_samples", list_id=list_id)
        return {
            "list_id": target,
            "best_weekday": None,
            "best_hour": None,
            "expected_open_rate": None,
            "samples": 0,
        }

    weighted: dict[tuple[int, int], tuple[float, int]] = {}
    for weekday, hour, rate, delivered in samples:
        cur_rate, cur_w = weighted.get((weekday, hour), (0.0, 0))
        new_w = cur_w + delivered
        new_rate = ((cur_rate * cur_w) + (rate * delivered)) / new_w
        weighted[(weekday, hour)] = (new_rate, new_w)

    (best_weekday, best_hour), (best_rate, best_volume) = max(
        weighted.items(), key=lambda kv: kv[1][0]
    )

    weekday_counts = Counter(s[0] for s in samples)
    hour_counts = Counter(s[1] for s in samples)

    weekday_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    result = {
        "list_id": target,
        "best_weekday": weekday_names[best_weekday],
        "best_weekday_index": best_weekday,
        "best_hour": best_hour,
        "expected_open_rate": round(best_rate, 6),
        "weighted_volume": best_volume,
        "samples": len(samples),
        "weekday_distribution": {weekday_names[k]: v for k, v in weekday_counts.items()},
        "hour_distribution": dict(hour_counts),
    }

    log.info(
        "brevo.get_best_send_time.done",
        list_id=target,
        best_weekday=result["best_weekday"],
        best_hour=best_hour,
        expected_open_rate=result["expected_open_rate"],
        samples=len(samples),
    )
    return result


__all__ = [
    "get_account_stats",
    "get_lists",
    "get_campaigns",
    "create_email_campaign",
    "send_campaign",
    "get_campaign_report",
    "add_contact",
    "get_best_send_time",
]


# Mantém referência usada implicitamente (silencia linters) -------------------
_ = date
