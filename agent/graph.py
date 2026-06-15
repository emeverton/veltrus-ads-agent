"""
Grafo LangGraph — Veltrus Ads Agent

Fluxo por conta de anúncios:
  START → analista ─(anomalias)──→ estrategista → revisor → executor → memorizador → END
                   └─(sem anomalias)──────────────────────────────────→ memorizador → END
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agent.config import settings
from agent.tools import google_ads, meta_ads, normalizer
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
_llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    max_tokens=4096,
)

# ---------------------------------------------------------------------------
# Estado compartilhado
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    # Input: contexto da conta sendo analisada
    account: dict   # linha de ad_accounts (id, platform, account_id, token, client_id)
    client: dict    # linha de clients (name, vertical, business_dna)

    # ANALISTA
    campaigns_analyzed: list[dict]
    anomalies: list[dict]

    # ESTRATEGISTA
    decision: dict          # {campaign_uuid, campaign_id, campaign_name, platform, action_type, params, reasoning}
    memory_context: list[dict]

    # REVISOR
    risk_level: str         # "LOW" | "MEDIUM" | "HIGH"
    risk_reasoning: str

    # EXECUTOR
    execution_result: dict

# ---------------------------------------------------------------------------
# Helper: loop de agente com tool use
# ---------------------------------------------------------------------------
async def _agent_loop(
    tools: list,
    system_prompt: str,
    user_prompt: str,
    max_iterations: int = 6,
) -> str:
    """Ciclo LLM → tool calls → resultados → LLM até resposta textual final."""
    tools_by_name = {t.name: t for t in tools}
    llm_bound = _llm.bind_tools(tools) if tools else _llm

    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    for _ in range(max_iterations):
        response = await llm_bound.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            return str(response.content)

        for tc in tool_calls:
            fn = tools_by_name.get(tc["name"])
            if fn is None:
                result: Any = {"error": f"ferramenta desconhecida: {tc['name']}"}
            else:
                result = await fn.ainvoke(tc["args"])
            messages.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=tc["id"],
                )
            )
    # se esgotar as iterações, retorna o último conteúdo textual disponível
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content)
    return ""


def _is_invalid_uuid(value: Any) -> bool:
    """Retorna True para qualquer valor que não seja UUID v4 válido."""
    if not value:
        return True
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return True
    return parsed.version != 4


def is_invalid_uuid(value: Any) -> bool:
    """Alias público usado por testes e integrações."""
    return _is_invalid_uuid(value)


def is_valid_uuid(value: Any) -> bool:
    """Compatibilidade: inverso de _is_invalid_uuid."""
    return not _is_invalid_uuid(value)


def _extract_json(text: str) -> dict:
    """Extrai o primeiro objeto JSON encontrado no texto."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end == 0:
        return {}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return {}

# ===========================================================================
# FERRAMENTAS — ANALISTA
# ===========================================================================
@tool
async def fetch_account_campaigns(ad_account_uuid: str | None) -> list[dict]:
    """Busca campanhas não-arquivadas de uma conta de anúncios pelo UUID interno."""
    if _is_invalid_uuid(ad_account_uuid):
        log.warning(
            "fetch_campaigns.skip",
            reason="invalid_uuid",
            value=ad_account_uuid,
        )
        return []
    result = (
        supabase.table("campaigns")
        .select("id, campaign_id, name, platform, status, daily_budget")
        .eq("account_id", ad_account_uuid)
        .neq("status", "archived")
        .execute()
    )
    return result.data or []


@tool
async def fetch_daily_metrics(campaign_uuid: str, platform: str = "meta", days: int = 7) -> list[dict]:
    """Busca métricas diárias normalizadas dos últimos N dias para uma campanha (UUID interno).

    Retorna lista de UnifiedMetrics com campos: spend_usd, impressions, clicks,
    conversions_click, conversions_view, revenue_usd, cpa_click, roas_click,
    ctr, attribution_window, confidence_score, data_source.
    platform: "meta" | "google" — necessário para normalização correta de seed data.
    """
    if _is_invalid_uuid(campaign_uuid):
        log.warning(
            "fetch_daily_metrics.skip",
            reason="invalid_uuid",
            value=campaign_uuid,
        )
        return []

    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    result = (
        supabase.table("daily_metrics")
        .select(
            "date, spend, impressions, clicks, conversions, cpa, roas, ctr, "
            "raw_payload, attribution_window, confidence_score"
        )
        .eq("campaign_id", campaign_uuid)
        .gte("date", since)
        .order("date", desc=False)
        .execute()
    )
    rows = result.data or []
    return [normalizer.normalize_supabase_row(row, platform) for row in rows]


@tool
async def fetch_meta_campaigns_live(ad_account_uuid: str) -> list[dict]:
    """Busca campanhas diretamente da Meta API (dados em tempo real).

    Retorna campanhas ativas e pausadas. Preferir sobre fetch_account_campaigns
    quando platform == 'meta'. Retorna lista vazia se a conta não tiver campanhas.
    """
    if _is_invalid_uuid(ad_account_uuid):
        log.warning(
            "fetch_meta_campaigns.skip",
            reason="invalid_uuid",
            value=ad_account_uuid,
        )
        return []
    row = (
        supabase.table("ad_accounts")
        .select("account_id, token")
        .eq("id", ad_account_uuid)
        .single()
        .execute()
    )
    account = row.data or {}
    return await meta_ads.list_campaigns(account["account_id"], account["token"])


@tool
async def fetch_meta_insights_live(
    ad_account_uuid: str,
    campaign_external_id: str,
    date_start: str,
    date_end: str,
) -> dict:
    """Busca métricas reais de uma campanha Meta via API (dados em tempo real).

    date_start / date_end: formato YYYY-MM-DD.
    Retorna spend, impressions, clicks, conversions, cpa, roas, ctr.
    Preferir sobre fetch_daily_metrics quando platform == 'meta'.
    """
    if _is_invalid_uuid(ad_account_uuid):
        log.warning(
            "fetch_meta_insights.skip",
            reason="invalid_uuid",
            value=ad_account_uuid,
        )
        return {}
    row = (
        supabase.table("ad_accounts")
        .select("account_id, token")
        .eq("id", ad_account_uuid)
        .single()
        .execute()
    )
    account = row.data or {}
    account_id_clean = account["account_id"].replace("act_", "")
    ds = datetime.strptime(date_start, "%Y-%m-%d").date()
    de = datetime.strptime(date_end, "%Y-%m-%d").date()
    insights = await meta_ads.get_campaign_insights(
        account_id_clean, campaign_external_id, ds, de, account["token"]
    )
    return normalizer.normalize_insights(insights, platform="meta")


def _google_credentials(refresh_token: str = "") -> dict[str, Any]:
    """Monta as credenciais OAuth do Google Ads a partir do .env (+ refresh_token opcional)."""
    return {
        "client_id": settings.google_ads_client_id,
        "client_secret": settings.google_ads_client_secret,
        "refresh_token": refresh_token or settings.google_ads_refresh_token,
        "login_customer_id": settings.google_ads_login_customer_id or None,
    }


@tool
async def fetch_google_campaigns_live(customer_id: str) -> list[dict]:
    """Busca campanhas diretamente da Google Ads API (dados em tempo real).

    customer_id: ID da conta Google Ads (sem hífens). Usa as credenciais OAuth do .env.
    Retorna campanhas não-removidas com campaign_id, name, status, campaign_budget_id e
    daily_budget_usd. Preferir sobre fetch_account_campaigns quando platform == 'google'.
    """
    log.info("google.list_campaigns.start", customer_id=customer_id)
    try:
        campaigns = await google_ads.get_campaigns(customer_id, _google_credentials())
    except Exception as exc:
        log.error("google.list_campaigns.failed", customer_id=customer_id, error=str(exc))
        return []
    log.info("google.list_campaigns.done", customer_id=customer_id, total=len(campaigns))
    return campaigns

# ===========================================================================
# FERRAMENTAS — ESTRATEGISTA
# ===========================================================================
@tool
async def search_agent_memory(
    query_text: str,
    campaign_uuid: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Busca memórias relevantes por correspondência textual no campo content.

    campaign_uuid: filtra por campanha específica (None = busca global).
    Substitui similarity search vetorial até o serviço de embeddings ser integrado.
    """
    qb = (
        supabase.table("agent_memory")
        .select("id, content, memory_type, created_at, campaign_id")
        .ilike("content", f"%{query_text[:80]}%")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if campaign_uuid and _is_invalid_uuid(campaign_uuid):
        log.warning(
            "search_agent_memory.skip_campaign_filter",
            reason="invalid_uuid",
            value=campaign_uuid,
        )
    elif campaign_uuid:
        qb = qb.eq("campaign_id", campaign_uuid)
    result = qb.execute()
    return result.data or []

# ===========================================================================
# FERRAMENTAS — EXECUTOR
# ===========================================================================
@tool
async def save_decision(
    campaign_uuid: str,
    action_type: str,
    reasoning: str,
    payload: dict,
    executed: bool,
    approved_by: str | None = None,
) -> dict:
    """Registra uma decisão do agente em agent_decisions e retorna a linha criada."""
    if _is_invalid_uuid(campaign_uuid):
        log.warning(
            "estrategista.skip",
            reason="invalid_uuid",
            value=campaign_uuid,
            action_type=action_type,
        )
        return {
            "skipped": True,
            "reason": "invalid_campaign_uuid",
            "value": campaign_uuid,
        }

    row: dict[str, Any] = {
        "campaign_id": campaign_uuid,
        "action_type": action_type,
        "reasoning": reasoning,
        "payload": payload,
        "executed": executed,
        "approved_by": approved_by,
        "approved_at": datetime.utcnow().isoformat() if executed else None,
    }
    result = supabase.table("agent_decisions").insert(row).execute()
    log.info(
        "executor.decision_saved",
        action_type=action_type,
        executed=executed,
        campaign_uuid=campaign_uuid,
    )
    return result.data[0] if result.data else {}


@tool
async def run_meta_action(
    action_type: str,
    campaign_external_id: str,
    account_external_id: str,
    daily_budget_usd: float | None = None,
) -> dict:
    """Executa uma ação via Meta Ads API.

    O token de acesso é buscado internamente pelo account_external_id.
    action_type: pause_campaign | activate_campaign | budget_increase | budget_decrease
    daily_budget_usd: obrigatório para ações de budget.
    """
    token_row = (
        supabase.table("ad_accounts")
        .select("token")
        .eq("account_id", account_external_id)
        .eq("platform", "meta")
        .single()
        .execute()
    )
    token = (token_row.data or {}).get("token", "")

    if action_type == "pause_campaign":
        return await meta_ads.pause_campaign(campaign_external_id, token)
    if action_type == "activate_campaign":
        return await meta_ads.activate_campaign(campaign_external_id, token)
    if action_type in ("budget_increase", "budget_decrease"):
        if daily_budget_usd is None:
            return {"error": "daily_budget_usd obrigatório para ações de budget"}
        return await meta_ads.update_campaign_budget(campaign_external_id, daily_budget_usd, token)
    return {"error": f"action_type desconhecido: {action_type}"}


@tool
async def run_google_action(
    action_type: str,
    customer_id: str,
    campaign_external_id: str,
    account_external_id: str,
    campaign_budget_id: str | None = None,
    amount_micros: int | None = None,
) -> dict:
    """Executa uma ação via Google Ads API.

    Credenciais OAuth são compostas com o refresh_token armazenado em ad_accounts.token.
    action_type: pause_campaign | activate_campaign | budget_increase | budget_decrease
    amount_micros: obrigatório para ações de budget (USD * 1_000_000).
    """
    # Modo somente-leitura: registra a intenção mas NÃO chama a API do Google.
    if settings.google_ads_read_only:
        log.info(
            "google.action.read_only_skip",
            action_type=action_type,
            customer_id=customer_id,
            campaign_external_id=campaign_external_id,
        )
        return {
            "executed": False,
            "read_only": True,
            "action_type": action_type,
            "customer_id": customer_id,
            "campaign_external_id": campaign_external_id,
            "note": "GOOGLE_ADS_READ_ONLY=true — ação registrada mas não executada na API Google",
        }

    # refresh_token vem da conta no Supabase; cai para o .env quando não houver linha.
    refresh_token = ""
    try:
        token_row = (
            supabase.table("ad_accounts")
            .select("token")
            .eq("account_id", account_external_id)
            .eq("platform", "google")
            .maybe_single()
            .execute()
        )
        refresh_token = ((token_row.data if token_row else None) or {}).get("token", "")
    except Exception as exc:  # pragma: no cover - rede/DB
        log.warning("google.action.token_lookup_failed", error=str(exc))
    if not refresh_token:
        refresh_token = settings.google_ads_refresh_token
    credentials = {
        "client_id": settings.google_ads_client_id,
        "client_secret": settings.google_ads_client_secret,
        "refresh_token": refresh_token,
        "login_customer_id": settings.google_ads_login_customer_id or None,
    }

    if action_type == "pause_campaign":
        return await google_ads.pause_campaign(customer_id, campaign_external_id, credentials)
    if action_type == "activate_campaign":
        return await google_ads.activate_campaign(customer_id, campaign_external_id, credentials)
    if action_type in ("budget_increase", "budget_decrease"):
        if campaign_budget_id is None or amount_micros is None:
            return {"error": "campaign_budget_id e amount_micros obrigatórios para ações de budget"}
        return await google_ads.update_campaign_budget(
            customer_id, campaign_budget_id, amount_micros, credentials
        )
    return {"error": f"action_type desconhecido: {action_type}"}


@tool
async def notify_human(
    campaign_name: str,
    action_type: str,
    risk_level: str,
    reasoning: str,
    decision_id: str,
) -> dict:
    """Notifica um humano via webhook (n8n → WhatsApp) para aprovar ou rejeitar a ação.

    Se N8N_WEBHOOK_URL não estiver configurado, apenas loga o alerta.
    """
    log.warning(
        "executor.human_approval_required",
        campaign_name=campaign_name,
        action_type=action_type,
        risk_level=risk_level,
        decision_id=decision_id,
    )

    webhook_url = settings.n8n_webhook_url
    if not webhook_url:
        return {
            "notification_sent": False,
            "channel": "log_only",
            "message": (
                f"[{risk_level}] Campanha '{campaign_name}': "
                f"ação '{action_type}' aguarda aprovação. ID: {decision_id}"
            ),
        }

    payload = {
        "decision_id":   decision_id,
        "campaign_name": campaign_name,
        "action_type":   action_type,
        "risk_level":    risk_level,
        "reasoning":     reasoning,
        "phone_number":  settings.notify_phone_number,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        log.info("executor.webhook_sent", decision_id=decision_id, status=resp.status_code)
        return {"notification_sent": True, "channel": "n8n_webhook", "http_status": resp.status_code}
    except Exception as exc:
        log.error("executor.webhook_failed", decision_id=decision_id, error=str(exc))
        return {"notification_sent": False, "channel": "n8n_webhook", "error": str(exc)}

# ===========================================================================
# FERRAMENTAS — MEMORIZADOR
# ===========================================================================
@tool
async def save_memory(
    content: str,
    memory_type: str,
    campaign_uuid: str | None = None,
) -> dict:
    """Salva um insight ou observação em agent_memory para ciclos futuros.

    memory_type: observation | pattern | rule | context
    campaign_uuid: None = memória global; UUID = específica da campanha.
    embedding é null por enquanto — será preenchido quando o serviço de embeddings for integrado.
    """
    safe_campaign_uuid = campaign_uuid if not _is_invalid_uuid(campaign_uuid) else None
    if campaign_uuid and safe_campaign_uuid is None:
        log.warning("memorizador.invalid_campaign_uuid", value=campaign_uuid)

    row: dict[str, Any] = {
        "content": content,
        "memory_type": memory_type,
        "campaign_id": safe_campaign_uuid,
    }
    result = supabase.table("agent_memory").insert(row).execute()
    log.info("memorizador.memory_saved", memory_type=memory_type, campaign_uuid=safe_campaign_uuid)
    return result.data[0] if result.data else {}

# ===========================================================================
# NÓ 1: ANALISTA
# ===========================================================================
_ANALISTA_SYSTEM = """
Você é o ANALISTA do Veltrus Ads Agent.

Função: buscar métricas dos últimos 7 dias das campanhas de uma conta de anúncios,
calcular estatísticas e identificar anomalias de performance.

Todos os dados retornados pelas ferramentas já estão normalizados no Unified Marketing Schema.
Use SEMPRE os campos normalizados para análise:
  - conversions_click  (não "conversions" — exclui view-through)
  - cpa_click          (spend / conversions_click)
  - roas_click         (revenue_usd / spend_usd)
  - confidence_score   (0.0–1.0): pese anomalias com score < 0.6 com cautela
  - attribution_window: inclua no contexto da decisão

Thresholds de anomalia (aplicar a campanhas com ao menos 3 dias de dados e confidence_score >= 0.4):
- cpa_spike:     cpa_click do último dia  > média 7 dias × 1.5
- roas_negative: roas_click do último dia < 1.0
- ctr_drop:      ctr do último dia        < média 7 dias × 0.70  (queda > 30%)

Estratégia de coleta (siga esta ordem de prioridade):

Para platform == 'meta':
  1. fetch_meta_campaigns_live → campanhas em tempo real da Meta API
  2. Se lista vazia, use fetch_account_campaigns → campanhas do Supabase
  3. Para cada campanha: fetch_meta_insights_live (retorna UnifiedMetrics normalizado)
  4. Se spend_usd == 0, use fetch_daily_metrics(campaign_uuid, platform="meta")

Para platform == 'google':
  1. fetch_google_campaigns_live(customer_id) → campanhas em tempo real da Google Ads API
     (customer_id = ID externo da conta). Loga google.list_campaigns.start.
  2. Se lista vazia e houver UUID interno válido da conta, use fetch_account_campaigns → campanhas do Supabase.
     Se o UUID interno estiver "não disponível", NÃO chame fetch_account_campaigns.
  3. Para cada campanha: fetch_daily_metrics(campaign_uuid, platform="google")

Para outras plataformas:
  1. fetch_account_campaigns → campanhas do Supabase
  2. fetch_daily_metrics(campaign_uuid, platform="google"|"meta")

Após coletar, calcule médias dos 7 dias e identifique anomalias.

Retorne EXCLUSIVAMENTE um JSON (sem markdown, sem texto fora do JSON):
{
  "campaigns_analyzed": [
    {
      "campaign_uuid": "uuid-interno",
      "campaign_id": "id-externo-plataforma",
      "name": "Nome da campanha",
      "platform": "meta|google",
      "data_source": "meta_api|supabase|seed",
      "attribution_window": "7d_click_1d_view",
      "avg_confidence": 0.75,
      "avg_cpa_click": 12.50,
      "avg_roas_click": 2.1,
      "avg_ctr": 0.032,
      "last_spend_usd": 45.0
    }
  ],
  "anomalies": [
    {
      "campaign_uuid": "uuid-interno",
      "campaign_id": "id-externo-plataforma",
      "name": "Nome",
      "platform": "meta|google",
      "anomaly_type": "cpa_spike|roas_negative|ctr_drop",
      "severity": "high|medium",
      "current_value": 28.5,
      "avg_value": 12.5,
      "threshold": 18.75,
      "last_spend_usd": 45.0,
      "confidence_score": 0.40
    }
  ]
}
""".strip()


def _account_internal_uuid(account: dict) -> str | None:
    """UUID interno da conta (ad_accounts.id), ou None se indisponível/inválido."""
    raw = account.get("id")
    if raw is None:
        return None
    candidate = str(raw).strip()
    return candidate if not _is_invalid_uuid(candidate) else None


async def analista_node(state: AgentState) -> dict:
    account = state["account"]
    log.info("analista.start", account_id=account.get("account_id"), platform=account.get("platform"))

    date_end   = datetime.utcnow().date()
    date_start = date_end - timedelta(days=7)

    internal_uuid = _account_internal_uuid(account)
    if internal_uuid:
        uuid_line = f"- UUID interno da conta (ad_account): {internal_uuid}"
    else:
        uuid_line = (
            "- UUID interno da conta: indisponível (conta sintetizada via .env). "
            "NÃO chame fetch_account_campaigns nem fetch_meta_campaigns_live."
        )

    user_prompt = f"""
Analise as campanhas desta conta:
{uuid_line}
- Plataforma: {account["platform"]}
- ID externo da conta: {account["account_id"]}
- Cliente: {state["client"].get("name", "N/A")} ({state["client"].get("vertical", "")})
- Período de análise: {date_start} até {date_end}

Siga a estratégia de coleta definida no sistema e retorne o JSON.
""".strip()

    raw = await _agent_loop(
        tools=[
            fetch_account_campaigns,
            fetch_daily_metrics,
            fetch_meta_campaigns_live,
            fetch_meta_insights_live,
            fetch_google_campaigns_live,
        ],
        system_prompt=_ANALISTA_SYSTEM,
        user_prompt=user_prompt,
    )

    parsed = _extract_json(raw)
    campaigns_analyzed: list[dict] = parsed.get("campaigns_analyzed", [])
    anomalies: list[dict] = parsed.get("anomalies", [])

    log.info(
        "analista.done",
        campaigns_analyzed=len(campaigns_analyzed),
        anomalies=len(anomalies),
    )
    return {"campaigns_analyzed": campaigns_analyzed, "anomalies": anomalies}

# ===========================================================================
# NÓ 2: ESTRATEGISTA
# ===========================================================================
_ESTRATEGISTA_SYSTEM = """
Você é o ESTRATEGISTA do Veltrus Ads Agent.

Função: receber anomalias detectadas pelo ANALISTA, consultar memória histórica
e decidir a melhor ação. Foque na anomalia mais crítica (maior severity + maior spend).

Ações disponíveis:
- budget_increase:   aumentar budget (quando ROAS > 1.5 e há margem de escala)
- budget_decrease:   reduzir budget (controle de CPA elevado)
- pause_campaign:    pausar (CPA > 3× média OU ROAS < 0.5 — ação drástica)
- activate_campaign: ativar campanha pausada que melhorou
- monitor_only:      monitorar sem ação — quando dados são insuficientes ou tendência incerta

Passos:
1. search_agent_memory com palavras-chave da anomalia para buscar padrões históricos
2. Analise anomalias + memória + contexto do cliente
3. Decida a ação mais adequada

Retorne EXCLUSIVAMENTE um JSON:
{
  "campaign_uuid": "uuid-interno",
  "campaign_id": "id-externo-plataforma",
  "campaign_name": "Nome",
  "platform": "meta|google",
  "action_type": "budget_increase|budget_decrease|pause_campaign|activate_campaign|monitor_only",
  "params": {
    "new_budget_usd": 150.0,
    "budget_change_pct": 15.0
  },
  "reasoning": "Raciocínio detalhado da decisão, incluindo referências ao histórico..."
}
""".strip()


async def estrategista_node(state: AgentState) -> dict:
    anomalies = state["anomalies"]
    client = state["client"]
    log.info("estrategista.start", anomalies_count=len(anomalies))

    user_prompt = f"""
Anomalias detectadas pelo ANALISTA:
{json.dumps(anomalies, indent=2, default=str)}

Contexto do cliente:
- Nome: {client.get("name")}
- Vertical: {client.get("vertical")}
- DNA do negócio: {json.dumps(client.get("business_dna", {}), ensure_ascii=False)}

Limites configurados:
- Mudança máxima de budget por ciclo: {settings.agent_max_budget_change_pct}%
- Limite de gasto diário: ${settings.agent_max_daily_spend_usd}

Use search_agent_memory para buscar padrões históricos e decida a ação.
Retorne o JSON conforme especificado.
""".strip()

    raw = await _agent_loop(
        tools=[search_agent_memory],
        system_prompt=_ESTRATEGISTA_SYSTEM,
        user_prompt=user_prompt,
    )

    parsed = _extract_json(raw)
    if not parsed.get("action_type"):
        parsed = {"action_type": "monitor_only", "reasoning": raw, "campaign_uuid": "", "params": {}}

    if _is_invalid_uuid(parsed.get("campaign_uuid")):
        recovered = _recover_campaign_uuid(parsed, anomalies)
        if recovered:
            log.info(
                "estrategista.campaign_uuid_recovered",
                value=parsed.get("campaign_uuid"),
                recovered=recovered,
            )
            parsed["campaign_uuid"] = recovered
        else:
            log.warning(
                "estrategista.invalid_campaign_uuid",
                value=parsed.get("campaign_uuid"),
                action_type=parsed.get("action_type"),
            )
            parsed["campaign_uuid"] = None
            parsed["action_type"] = "monitor_only"

    log.info("estrategista.done", action_type=parsed.get("action_type"))
    return {"decision": parsed, "memory_context": []}


def _recover_campaign_uuid(decision: dict, anomalies: list[dict]) -> str | None:
    """Tenta recuperar um campaign_uuid válido casando a decisão com as anomalias."""
    ext_id = str(decision.get("campaign_id") or "").strip()
    name = str(decision.get("campaign_name") or "").strip()

    for anomaly in anomalies:
        candidate = anomaly.get("campaign_uuid")
        if _is_invalid_uuid(candidate):
            continue
        if ext_id and str(anomaly.get("campaign_id") or "").strip() == ext_id:
            return candidate
        if name and str(anomaly.get("name") or "").strip() == name:
            return candidate

    valid = [a.get("campaign_uuid") for a in anomalies if not _is_invalid_uuid(a.get("campaign_uuid"))]
    if len(valid) == 1:
        return valid[0]
    return None

# ===========================================================================
# NÓ 3: REVISOR
# ===========================================================================
_REVISOR_SYSTEM = """
Você é o REVISOR do Veltrus Ads Agent.

Função: avaliar o risco financeiro da decisão do ESTRATEGISTA e classificar como LOW / MEDIUM / HIGH.

Critérios (aplique o critério mais restritivo que se encaixar):
- HIGH:   pause_campaign com last_spend_usd > 100
          OU qualquer mudança de budget > 20% com spend > 200/dia
- MEDIUM: pause_campaign com last_spend_usd entre 50 e 100
          OU mudança de budget > 20% (qualquer spend)
          OU budget_decrease que reduz em mais de 30%
- LOW:    qualquer outra ação, incluindo monitor_only

Retorne EXCLUSIVAMENTE um JSON:
{
  "risk_level": "LOW|MEDIUM|HIGH",
  "risk_reasoning": "Justificativa objetiva com os números que fundamentam o nível de risco",
  "estimated_impact_usd": 50.0
}
""".strip()


async def revisor_node(state: AgentState) -> dict:
    decision = state["decision"]
    log.info("revisor.start", action_type=decision.get("action_type"))

    # Enriquece o contexto com spend da campanha-alvo
    target_anomaly = next(
        (a for a in state.get("anomalies", []) if a.get("campaign_uuid") == decision.get("campaign_uuid")),
        {},
    )

    user_prompt = f"""
Decisão do ESTRATEGISTA:
{json.dumps(decision, indent=2, default=str)}

Dados da campanha afetada:
{json.dumps(target_anomaly, indent=2, default=str)}

Limite de mudança de budget configurado: {settings.agent_max_budget_change_pct}%
Limite de gasto diário da conta: ${settings.agent_max_daily_spend_usd}

Classifique o risco e retorne o JSON.
""".strip()

    raw = await _agent_loop(
        tools=[],
        system_prompt=_REVISOR_SYSTEM,
        user_prompt=user_prompt,
    )

    parsed = _extract_json(raw)
    risk_level = parsed.get("risk_level", "HIGH")
    risk_reasoning = parsed.get("risk_reasoning", raw[:500])

    log.info("revisor.done", risk_level=risk_level)
    return {"risk_level": risk_level, "risk_reasoning": risk_reasoning}

# ===========================================================================
# NÓ 4: EXECUTOR
# ===========================================================================
_EXECUTOR_SYSTEM = """
Você é o EXECUTOR do Veltrus Ads Agent.

Função: executar ou enfileirar a decisão com base no risco classificado.

Regras de execução:
- risk_level == LOW  E autonomous_mode == true  → execute a ação via API (run_meta_action ou run_google_action)
                                                   depois salve com save_decision(executed=true, approved_by="autonomous")
- risk_level == LOW  E autonomous_mode == false → save_decision(executed=false) + notify_human
- risk_level == MEDIUM ou HIGH                  → save_decision(executed=false) + notify_human

Passos obrigatórios:
1. Sempre chame save_decision para registrar a decisão
2. Se executar via API: chame a ferramenta de API primeiro, depois save_decision com o resultado no payload
3. Se não executar: save_decision com executed=false, depois notify_human

Ferramentas disponíveis:
- save_decision     → registra em agent_decisions
- run_meta_action   → executa ação Meta Ads (busca o token internamente via account_external_id)
- run_google_action → executa ação Google Ads (busca credenciais internamente)
- notify_human      → envia notificação de aprovação (placeholder)

Retorne EXCLUSIVAMENTE um JSON:
{
  "executed": true|false,
  "decision_id": "uuid-da-decisao",
  "notification_sent": true|false,
  "api_result": {}
}
""".strip()


async def executor_node(state: AgentState) -> dict:
    decision = state["decision"]
    risk_level = state["risk_level"]
    account = state["account"]

    log.info(
        "executor.start",
        action_type=decision.get("action_type"),
        risk_level=risk_level,
        autonomous=settings.agent_autonomous_mode,
    )

    user_prompt = f"""
Decisão a processar:
{json.dumps(decision, indent=2, default=str)}

Risco classificado: {risk_level}
Risk reasoning: {state.get("risk_reasoning", "")}

Contexto da conta:
- Plataforma: {account["platform"]}
- ID externo da conta: {account["account_id"]}
- autonomous_mode: {settings.agent_autonomous_mode}

Siga as regras de execução e retorne o JSON de resultado.
""".strip()

    raw = await _agent_loop(
        tools=[save_decision, run_meta_action, run_google_action, notify_human],
        system_prompt=_EXECUTOR_SYSTEM,
        user_prompt=user_prompt,
    )

    result = _extract_json(raw)
    if not result:
        result = {"executed": False, "raw_response": raw[:500]}

    log.info(
        "executor.done",
        executed=result.get("executed"),
        risk_level=risk_level,
    )
    return {"execution_result": result}

# ===========================================================================
# NÓ 5: MEMORIZADOR
# ===========================================================================
_MEMORIZADOR_SYSTEM = """
Você é o MEMORIZADOR do Veltrus Ads Agent.

Função: consolidar os aprendizados do ciclo atual em agent_memory para enriquecer
decisões futuras.

Tipos de memória:
- observation: fato isolado observado neste ciclo
- pattern:     comportamento recorrente ou tendência identificada
- rule:        causa-efeito confirmado ("quando X → fazer Y")
- context:     informação de contexto duradoura sobre a campanha ou cliente

Diretrizes:
- Salve de 1 a 3 memórias por ciclo (qualidade > quantidade)
- Se não houve anomalias: salve uma observação de "performance estável"
- Se houve ação executada: salve o raciocínio + resultado como observation ou pattern
- Seja específico: inclua valores numéricos, nomes de campanhas e datas quando relevante

Use save_memory para cada memória. Ao terminar, retorne uma lista JSON:
[{"memory_type": "...", "content": "...", "campaign_uuid": "uuid|null"}]
""".strip()


async def memorizador_node(state: AgentState) -> dict:
    account = state["account"]
    log.info("memorizador.start", account_id=account.get("account_id"))

    user_prompt = f"""
Resumo do ciclo para a conta {account["account_id"]} ({account["platform"]}):

Campanhas analisadas ({len(state.get("campaigns_analyzed", []))} total):
{json.dumps(state.get("campaigns_analyzed", []), indent=2, default=str)}

Anomalias detectadas:
{json.dumps(state.get("anomalies", []), indent=2, default=str)}

Decisão do ESTRATEGISTA:
{json.dumps(state.get("decision", {}), indent=2, default=str)}

Nível de risco: {state.get("risk_level", "N/A")}
Risk reasoning: {state.get("risk_reasoning", "")}

Resultado da execução:
{json.dumps(state.get("execution_result", {}), indent=2, default=str)}

Salve as memórias relevantes e retorne o JSON de confirmação.
""".strip()

    await _agent_loop(
        tools=[save_memory],
        system_prompt=_MEMORIZADOR_SYSTEM,
        user_prompt=user_prompt,
    )

    log.info("memorizador.done", account_id=account.get("account_id"))
    return {}

# ===========================================================================
# Roteamento condicional após ANALISTA
# ===========================================================================
def _route_after_analista(state: AgentState) -> str:
    """Vai para ESTRATEGISTA se há anomalias; caso contrário pula para MEMORIZADOR."""
    if state.get("anomalies"):
        return "estrategista"
    return "memorizador"

# ===========================================================================
# Construção e compilação do grafo
# ===========================================================================
def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("analista", analista_node)
    graph.add_node("estrategista", estrategista_node)
    graph.add_node("revisor", revisor_node)
    graph.add_node("executor", executor_node)
    graph.add_node("memorizador", memorizador_node)

    graph.add_edge(START, "analista")
    graph.add_conditional_edges(
        "analista",
        _route_after_analista,
        {"estrategista": "estrategista", "memorizador": "memorizador"},
    )
    graph.add_edge("estrategista", "revisor")
    graph.add_edge("revisor", "executor")
    graph.add_edge("executor", "memorizador")
    graph.add_edge("memorizador", END)

    return graph


compiled_graph = build_graph().compile()
