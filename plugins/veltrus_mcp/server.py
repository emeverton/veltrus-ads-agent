"""
Veltrus Ads Agent — MCP server plugin.

Turns the Veltrus Ads Agent into a plugin: it exposes the agent's core
capabilities (the human-approval decision workflow and the agent run triggers)
as MCP tools, so any MCP client (Cursor, Claude Desktop, ...) can drive the
agent through natural language.

The plugin is a thin, decoupled client over the agent's FastAPI service — it does
not import the agent internals, so it stays lightweight and can point at a local
dev server or a deployed instance. All business logic (Supabase persistence,
Meta/Google execution on approval, LangGraph cycles) lives in the API and is
reused as-is.

Configuration (environment variables, also read from the repo .env if present):
    VELTRUS_API_URL   Base URL of the Veltrus API   (default: http://localhost:8000)
    VELTRUS_API_KEY   X-API-Key for the API         (falls back to API_SECRET_KEY)
    VELTRUS_TIMEOUT   Per-request timeout, seconds  (default: 30)

Run it directly over stdio:
    python -m plugins.veltrus_mcp.server
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

try:
    # Load the repo .env so API_SECRET_KEY / VELTRUS_* are available when present.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _api_url() -> str:
    return os.environ.get("VELTRUS_API_URL", "http://localhost:8000").rstrip("/")


def _api_key() -> str:
    return os.environ.get("VELTRUS_API_KEY") or os.environ.get("API_SECRET_KEY", "")


def _timeout() -> float:
    try:
        return float(os.environ.get("VELTRUS_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": _api_key(), "Content-Type": "application/json"}


mcp = FastMCP(
    "veltrus-ads-agent",
    instructions=(
        "Tools to operate the Veltrus Ads Agent: inspect the agent's pending "
        "optimization decisions, approve or reject them (human-in-the-loop), and "
        "trigger agent analysis cycles for Meta/Google Ads and email marketing."
    ),
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
async def _request(method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the Veltrus API and return a normalized result dict (never raises)."""
    url = f"{_api_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.request(method, url, json=json, headers=_auth_headers())
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "error": "connection_error",
            "detail": f"Could not reach Veltrus API at {url}: {exc}",
            "hint": "Is the API running? Set VELTRUS_API_URL to the right host.",
        }

    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}

    if resp.is_success:
        return {"ok": True, "status_code": resp.status_code, "data": payload}

    return {
        "ok": False,
        "error": "api_error",
        "status_code": resp.status_code,
        "detail": payload,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def check_health() -> dict[str, Any]:
    """Check whether the Veltrus Ads Agent API is reachable and healthy.

    Returns the service status and version. Use this first to confirm
    connectivity before calling other tools.
    """
    return await _request("GET", "/health")


@mcp.tool()
async def list_pending_decisions() -> dict[str, Any]:
    """List the agent's optimization decisions that are awaiting human approval.

    Each decision includes its action_type (e.g. budget_increase, pause_campaign),
    the agent's reasoning, the proposed payload, and the related campaign and ad
    account. Use this to review what the agent wants to do before approving.
    """
    return await _request("GET", "/decisions")


@mcp.tool()
async def approve_decision(decision_id: str, approved_by: str = "mcp") -> dict[str, Any]:
    """Approve a pending decision and execute it on the ad platform (Meta/Google).

    Args:
        decision_id: UUID of the decision (from list_pending_decisions).
        approved_by: Who approved it (email or identifier); recorded for audit.

    This triggers the real platform action (budget change, pause, etc.) and marks
    the decision as executed.
    """
    return await _request(
        "PATCH",
        f"/decisions/{decision_id}/approve",
        json={"approved_by": approved_by},
    )


@mcp.tool()
async def reject_decision(
    decision_id: str,
    reason: str,
    rejected_by: str = "mcp",
) -> dict[str, Any]:
    """Reject a pending decision. No platform action is taken.

    Args:
        decision_id: UUID of the decision (from list_pending_decisions).
        reason: Why the decision is being rejected (recorded for audit).
        rejected_by: Who rejected it (email or identifier).
    """
    return await _request(
        "PATCH",
        f"/decisions/{decision_id}/reject",
        json={"rejected_by": rejected_by, "reason": reason},
    )


@mcp.tool()
async def trigger_agent_run() -> dict[str, Any]:
    """Trigger one full agent analysis cycle for all active ad accounts.

    The agent collects metrics, analyzes performance and proposes optimization
    decisions (which then appear in list_pending_decisions). Runs in the
    background on the server and returns immediately.
    """
    return await _request("POST", "/run")


@mcp.tool()
async def trigger_email_campaign(
    client_id: str,
    list_id: int,
    context: str = "",
) -> dict[str, Any]:
    """Trigger the email-marketing agent for a client.

    Args:
        client_id: UUID of the client in the clients table.
        list_id: Brevo contact list ID to target.
        context: Optional extra context for the research/copywriter nodes.

    Runs the email LangGraph in the background and returns immediately.
    """
    return await _request(
        "POST",
        "/run-email",
        json={"client_id": client_id, "list_id": list_id, "context": context},
    )


def main() -> None:
    """Entry point — runs the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
