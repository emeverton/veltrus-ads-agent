"""
Grafo LangGraph — Veltrus Email Marketing Agent

Fluxo sequencial por cliente:
  START → pesquisador → analista_de_lista → copywriter → otimizador
        → executor → analista_de_resultados → END
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agent.config import settings
from agent.tools import email_brevo
from agent.tools.supabase_client import supabase

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM (web search habilitado para o PESQUISADOR via tool nativa Anthropic)
# ---------------------------------------------------------------------------
_llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    max_tokens=4096,
)

_llm_with_web_search = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    max_tokens=4096,
).bind_tools([{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}])


# ---------------------------------------------------------------------------
# Estado compartilhado
# ---------------------------------------------------------------------------
class EmailAgentState(TypedDict):
    # Input
    client: dict                 # linha de clients (id, name, vertical, business_dna)

    # PESQUISADOR
    briefing: dict               # {market_summary, competitor_signals, trends, hooks}

    # ANALISTA_DE_LISTA
    analysis: dict               # {list_id, recommended_segment, best_weekday, best_hour, baseline_metrics}

    # COPYWRITER
    copy_variants: list[dict]    # [{subject, preheader}, ...] (3 variações)
    html_content: str            # corpo único em HTML

    # OTIMIZADOR
    scheduled_at: str            # ISO 8601 final

    # EXECUTOR
    campaign_id: int | None      # campaign_id_brevo
    db_row_id: str | None        # uuid de email_campaigns

    # ANALISTA_DE_RESULTADOS
    report: dict


# ---------------------------------------------------------------------------
# Helper: loop de agente com tool use
# ---------------------------------------------------------------------------
async def _agent_loop(
    tools: list,
    system_prompt: str,
    user_prompt: str,
    max_iterations: int = 6,
    use_web_search: bool = False,
) -> str:
    tools_by_name = {t.name: t for t in tools}
    if use_web_search:
        # Web search é uma server-tool nativa Anthropic — combinamos com tools custom
        anth_web = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
        llm_bound = _llm.bind_tools([*tools, anth_web]) if tools else _llm.bind_tools([anth_web])
    else:
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
                # web_search é resolvida pela própria Anthropic; demais ferramentas
                # desconhecidas viram erro estruturado para o LLM corrigir
                continue
            result: Any = await fn.ainvoke(tc["args"])
            messages.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=tc["id"],
                )
            )
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content)
    return ""


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end == 0:
        return {}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return {}


def _extract_html(text: str) -> str:
    """Extrai bloco ```html ... ``` ou retorna o texto inteiro como fallback."""
    marker = "```html"
    if marker in text:
        start = text.find(marker) + len(marker)
        end = text.find("```", start)
        if end > start:
            return text[start:end].strip()
    if "<html" in text.lower() or "<body" in text.lower():
        return text.strip()
    return text.strip()


# ===========================================================================
# FERRAMENTAS — ANALISTA_DE_LISTA
# ===========================================================================
@tool
async def fetch_recent_campaigns(limit: int = 10) -> list[dict]:
    """Retorna as últimas N campanhas de email com métricas globais."""
    return await email_brevo.get_campaigns(limit=limit)


@tool
async def fetch_best_send_time(list_id: int) -> dict:
    """Analisa o histórico da lista e retorna o melhor weekday/hour para envio."""
    return await email_brevo.get_best_send_time(list_id=list_id)


@tool
async def fetch_lists() -> list[dict]:
    """Lista todas as listas de contatos da conta Brevo."""
    return await email_brevo.get_lists()


# ===========================================================================
# FERRAMENTAS — EXECUTOR
# ===========================================================================
@tool
async def create_brevo_campaign(
    name: str,
    subject: str,
    html_content: str,
    list_id: int,
    scheduled_at: str | None = None,
) -> dict:
    """Cria uma campanha de email no Brevo (rascunho ou agendada)."""
    return await email_brevo.create_email_campaign(
        name=name,
        subject=subject,
        html_content=html_content,
        list_id=list_id,
        scheduled_at=scheduled_at,
    )


@tool
async def send_brevo_campaign(campaign_id: int) -> dict:
    """Dispara imediatamente uma campanha em rascunho no Brevo."""
    return await email_brevo.send_campaign(campaign_id=campaign_id)


@tool
async def save_email_campaign_row(
    client_id: str,
    campaign_id_brevo: int,
    subject: str,
    name: str,
    list_id: int,
    html_content: str,
    copy_variants: list[dict],
    briefing: dict,
    analysis: dict,
    scheduled_at: str | None,
    sent_at: str | None,
) -> dict:
    """Insere/atualiza a linha em email_campaigns e retorna o registro."""
    row: dict[str, Any] = {
        "client_id": client_id,
        "campaign_id_brevo": campaign_id_brevo,
        "subject": subject,
        "name": name,
        "list_id": list_id,
        "html_content": html_content,
        "copy_variants": copy_variants,
        "briefing": briefing,
        "analysis": analysis,
        "scheduled_at": scheduled_at,
        "sent_at": sent_at,
    }
    result = (
        supabase.table("email_campaigns")
        .upsert(row, on_conflict="campaign_id_brevo")
        .execute()
    )
    log.info("email.executor.row_saved", campaign_id_brevo=campaign_id_brevo)
    return result.data[0] if result.data else {}


# ===========================================================================
# FERRAMENTAS — ANALISTA_DE_RESULTADOS
# ===========================================================================
@tool
async def fetch_campaign_report(campaign_id: int) -> dict:
    """Métricas pós-disparo de uma campanha Brevo."""
    return await email_brevo.get_campaign_report(campaign_id=campaign_id)


@tool
async def update_email_campaign_report(
    campaign_id_brevo: int,
    report: dict,
) -> dict:
    """Atualiza a linha em email_campaigns com as métricas finais."""
    update = {
        "sent": report.get("sent"),
        "delivered": report.get("delivered"),
        "unique_opens": report.get("unique_opens"),
        "unique_clicks": report.get("unique_clicks"),
        "open_rate": report.get("open_rate"),
        "click_rate": report.get("click_rate"),
        "bounce_rate": report.get("bounce_rate"),
        "unsubscribe_rate": report.get("unsubscribe_rate"),
        "raw_report": report.get("raw_payload") or report,
        "report_fetched_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = (
        supabase.table("email_campaigns")
        .update(update)
        .eq("campaign_id_brevo", campaign_id_brevo)
        .execute()
    )
    log.info("email.results.row_updated", campaign_id_brevo=campaign_id_brevo)
    return result.data[0] if result.data else {}


@tool
async def save_email_memory(
    content: str,
    memory_type: str,
    client_id: str | None = None,
) -> dict:
    """Salva um aprendizado em agent_memory (escopo email marketing)."""
    row: dict[str, Any] = {
        "content": f"[email] {content}",
        "memory_type": memory_type,
        "campaign_id": None,  # email_campaigns ≠ campaigns; mantemos contexto via content
    }
    if client_id:
        row["content"] = f"[email|client={client_id}] {content}"
    result = supabase.table("agent_memory").insert(row).execute()
    log.info("email.memory.saved", memory_type=memory_type, client_id=client_id)
    return result.data[0] if result.data else {}


# ===========================================================================
# NÓ 1: PESQUISADOR
# ===========================================================================
_PESQUISADOR_SYSTEM = """
Você é o PESQUISADOR do Agente de Email Marketing da Veltrus.

Função: usar web search para mapear mercado, concorrentes, tendências e ganchos
de comunicação relevantes ao cliente. Foque em informação acionável para o COPYWRITER.

Diretrizes:
- Faça de 2 a 5 buscas web — priorize fontes recentes (últimos 90 dias)
- Identifique: ângulos de mensagem, dores do público, sazonalidade, ofertas que
  concorrentes estão pushando, exemplos de subject lines de alto desempenho no vertical
- NÃO invente dados — se não encontrar, marque como "unknown"

Retorne EXCLUSIVAMENTE um JSON (sem markdown):
{
  "market_summary": "Resumo conciso do estado atual do mercado/vertical",
  "competitor_signals": ["sinal 1", "sinal 2", "..."],
  "trends": ["tendência 1", "tendência 2", "..."],
  "hooks": ["gancho de copy 1", "gancho de copy 2", "..."],
  "subject_inspiration": ["exemplo subject 1", "exemplo subject 2"],
  "sources": ["url1", "url2"]
}
""".strip()


async def pesquisador_node(state: EmailAgentState) -> dict:
    client = state["client"]
    log.info("email.pesquisador.start", client_id=client.get("id"), vertical=client.get("vertical"))

    user_prompt = f"""
Cliente:
- Nome: {client.get("name")}
- Vertical: {client.get("vertical")}
- DNA do negócio: {json.dumps(client.get("business_dna", {}), ensure_ascii=False)}

Pesquise mercado, concorrentes e tendências relevantes para a próxima campanha de email
deste cliente. Use web_search e retorne o JSON conforme especificado.
""".strip()

    raw = await _agent_loop(
        tools=[],
        system_prompt=_PESQUISADOR_SYSTEM,
        user_prompt=user_prompt,
        use_web_search=True,
    )

    briefing = _extract_json(raw)
    if not briefing:
        briefing = {"market_summary": raw[:1000], "competitor_signals": [], "trends": [], "hooks": []}

    log.info(
        "email.pesquisador.done",
        client_id=client.get("id"),
        hooks=len(briefing.get("hooks", [])),
        trends=len(briefing.get("trends", [])),
    )
    return {"briefing": briefing}


# ===========================================================================
# NÓ 2: ANALISTA_DE_LISTA
# ===========================================================================
_ANALISTA_LISTA_SYSTEM = """
Você é o ANALISTA_DE_LISTA do Agente de Email Marketing.

Função: avaliar histórico da conta Brevo (últimas campanhas + horários) e
recomendar a lista-alvo, segmento e melhor horário para a próxima campanha.

Passos:
1. Chame fetch_lists para conhecer as listas disponíveis
2. Chame fetch_recent_campaigns(limit=10) para ver baseline de open/click rate
3. Para a lista mais relevante (maior unique_subscribers ou explicitada no business_dna),
   chame fetch_best_send_time(list_id) para obter weekday/hour ótimo

Retorne EXCLUSIVAMENTE um JSON:
{
  "list_id": 123,
  "list_name": "Newsletter Geral",
  "recommended_segment": "Descrição textual do segmento (ex: 'todos os engajados nos últimos 90 dias')",
  "best_weekday": "tue",
  "best_weekday_index": 1,
  "best_hour": 9,
  "expected_open_rate": 0.28,
  "baseline_metrics": {
    "avg_open_rate": 0.22,
    "avg_click_rate": 0.04,
    "campaigns_analyzed": 10
  }
}
""".strip()


async def analista_de_lista_node(state: EmailAgentState) -> dict:
    client = state["client"]
    log.info("email.analista_lista.start", client_id=client.get("id"))

    user_prompt = f"""
Cliente: {client.get("name")} ({client.get("vertical")})
DNA: {json.dumps(client.get("business_dna", {}), ensure_ascii=False)}

Use as ferramentas para descobrir a lista correta, calcular baseline e
horário ótimo. Retorne o JSON conforme especificado.
""".strip()

    raw = await _agent_loop(
        tools=[fetch_lists, fetch_recent_campaigns, fetch_best_send_time],
        system_prompt=_ANALISTA_LISTA_SYSTEM,
        user_prompt=user_prompt,
        max_iterations=8,
    )

    analysis = _extract_json(raw)
    log.info(
        "email.analista_lista.done",
        list_id=analysis.get("list_id"),
        best_weekday=analysis.get("best_weekday"),
        best_hour=analysis.get("best_hour"),
    )
    return {"analysis": analysis}


# ===========================================================================
# NÓ 3: COPYWRITER
# ===========================================================================
_COPYWRITER_SYSTEM = """
Você é o COPYWRITER do Agente de Email Marketing da Veltrus.

Função: gerar 3 variações de subject line + 1 corpo de email completo em HTML,
adaptados ao vertical e DNA do cliente.

Diretrizes para subjects:
- 3 variações distintas em estilo: (a) urgência/escassez, (b) curiosidade/pergunta, (c) benefício direto
- Máximo 60 caracteres cada
- Sem clickbait barato; respeite o tom do business_dna

Diretrizes para o HTML:
- HTML inline-styled, mobile-friendly, largura máxima 600px
- Estrutura: header simples → bloco principal com hook → CTA destacado → footer com unsubscribe placeholder {{unsubscribe}}
- Use os hooks e trends do briefing
- Tom adaptado ao vertical: ecommerce=conversão direta, saas=valor/educacional, b2b=consultivo, retail=ofertas

Retorne EXCLUSIVAMENTE um JSON neste formato (e nada mais):
{
  "name": "nome interno da campanha (ex: 'Newsletter Mai/26 - Cliente X')",
  "copy_variants": [
    {"variant": "urgency",     "subject": "...", "preheader": "..."},
    {"variant": "curiosity",   "subject": "...", "preheader": "..."},
    {"variant": "benefit",     "subject": "...", "preheader": "..."}
  ],
  "selected_subject": "subject recomendado dos 3 acima",
  "html_content": "<!doctype html>...HTML COMPLETO AQUI..."
}
""".strip()


async def copywriter_node(state: EmailAgentState) -> dict:
    client = state["client"]
    briefing = state.get("briefing", {})
    analysis = state.get("analysis", {})

    log.info("email.copywriter.start", client_id=client.get("id"))

    user_prompt = f"""
Cliente:
- Nome: {client.get("name")}
- Vertical: {client.get("vertical")}
- DNA: {json.dumps(client.get("business_dna", {}), ensure_ascii=False)}

Briefing do PESQUISADOR:
{json.dumps(briefing, indent=2, ensure_ascii=False, default=str)}

Análise do ANALISTA_DE_LISTA:
{json.dumps(analysis, indent=2, ensure_ascii=False, default=str)}

Gere 3 subjects + 1 HTML conforme especificado. Retorne o JSON completo.
""".strip()

    raw = await _agent_loop(
        tools=[],
        system_prompt=_COPYWRITER_SYSTEM,
        user_prompt=user_prompt,
        max_iterations=2,
    )

    parsed = _extract_json(raw)
    copy_variants = parsed.get("copy_variants") or []
    html_content = parsed.get("html_content") or _extract_html(raw)
    name = parsed.get("name") or f"{client.get('name', 'campanha')} - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    selected_subject = (
        parsed.get("selected_subject")
        or (copy_variants[0]["subject"] if copy_variants else "Novidades")
    )

    log.info(
        "email.copywriter.done",
        variants=len(copy_variants),
        html_chars=len(html_content),
    )
    return {
        "copy_variants": copy_variants,
        "html_content": html_content,
        "analysis": {**analysis, "campaign_name": name, "selected_subject": selected_subject},
    }


# ===========================================================================
# NÓ 4: OTIMIZADOR
# ===========================================================================
_OTIMIZADOR_SYSTEM = """
Você é o OTIMIZADOR do Agente de Email Marketing.

Função: validar timing/frequência/segmento e devolver o scheduled_at final em ISO 8601 (UTC).

Regras:
- Use best_weekday + best_hour da análise
- Se o próximo slot ideal estiver a menos de 2 horas do agora, pule para o slot da próxima semana
- NUNCA agende em janela 22h–06h (timezone do cliente; assuma UTC se não houver timezone)
- Se a lista tem < 100 inscritos, marque needs_human_review=true
- Se os últimos 7 dias já tiveram envio para a mesma lista, pule 3 dias adicionais (anti-fadiga)

Retorne EXCLUSIVAMENTE um JSON:
{
  "scheduled_at": "2026-05-12T09:00:00Z",
  "rationale": "Próxima terça às 9h UTC — slot histórico de maior open rate",
  "needs_human_review": false,
  "warnings": []
}
""".strip()


async def otimizador_node(state: EmailAgentState) -> dict:
    analysis = state.get("analysis", {})
    log.info("email.otimizador.start", list_id=analysis.get("list_id"))

    now_utc = datetime.now(timezone.utc)

    user_prompt = f"""
Análise da lista:
{json.dumps(analysis, indent=2, ensure_ascii=False, default=str)}

Agora (UTC): {now_utc.isoformat()}
Janela mínima de 2h até o envio.

Calcule o scheduled_at final e retorne o JSON.
""".strip()

    raw = await _agent_loop(
        tools=[],
        system_prompt=_OTIMIZADOR_SYSTEM,
        user_prompt=user_prompt,
        max_iterations=2,
    )

    parsed = _extract_json(raw)
    scheduled_at = parsed.get("scheduled_at")

    if not scheduled_at:
        # fallback: próxima ocorrência do best_weekday/best_hour
        best_idx = analysis.get("best_weekday_index")
        best_hour = analysis.get("best_hour")
        if isinstance(best_idx, int) and isinstance(best_hour, int):
            days_ahead = (best_idx - now_utc.weekday()) % 7
            target = (now_utc + timedelta(days=days_ahead)).replace(
                hour=best_hour, minute=0, second=0, microsecond=0
            )
            if target <= now_utc + timedelta(hours=2):
                target += timedelta(days=7)
            scheduled_at = target.isoformat(timespec="seconds").replace("+00:00", "Z")
        else:
            target = (now_utc + timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
            scheduled_at = target.isoformat(timespec="seconds").replace("+00:00", "Z")

    log.info("email.otimizador.done", scheduled_at=scheduled_at)
    return {"scheduled_at": scheduled_at}


# ===========================================================================
# NÓ 5: EXECUTOR
# ===========================================================================
_EXECUTOR_SYSTEM = """
Você é o EXECUTOR do Agente de Email Marketing.

Função: criar a campanha no Brevo e persistir a linha em email_campaigns.

Regras:
- Sempre use create_brevo_campaign com scheduled_at recebido (campanha agendada).
- NÃO chame send_brevo_campaign quando há scheduled_at (Brevo dispara sozinho na hora).
- Após criação, chame save_email_campaign_row com TODOS os campos (incluindo briefing, analysis e copy_variants).

Retorne EXCLUSIVAMENTE um JSON:
{
  "campaign_id": 12345,
  "db_row_id": "uuid",
  "scheduled_at": "2026-05-12T09:00:00Z",
  "status": "scheduled"
}
""".strip()


async def executor_node(state: EmailAgentState) -> dict:
    client = state["client"]
    analysis = state.get("analysis", {})
    log.info("email.executor.start", client_id=client.get("id"))

    name = analysis.get("campaign_name") or f"{client.get('name')} - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    subject = analysis.get("selected_subject") or (
        state.get("copy_variants", [{}])[0].get("subject") if state.get("copy_variants") else "Novidades"
    )

    user_prompt = f"""
Cliente UUID: {client.get("id")}
Lista alvo: {analysis.get("list_id")}
Nome da campanha: {name}
Subject selecionado: {subject}
Scheduled at: {state.get("scheduled_at")}

Tamanho do HTML: {len(state.get("html_content", ""))} chars
Subjects gerados: {json.dumps(state.get("copy_variants", []), ensure_ascii=False)}

Briefing: {json.dumps(state.get("briefing", {}), ensure_ascii=False)[:1500]}
Analysis: {json.dumps(analysis, ensure_ascii=False)[:1500]}

Crie a campanha no Brevo e salve a linha em email_campaigns.
""".strip()

    # Executor não usa LLM diretamente — chamadas determinísticas para evitar
    # alucinações em parâmetros críticos (list_id, client_id, scheduled_at).
    create_result = await email_brevo.create_email_campaign(
        name=name,
        subject=subject,
        html_content=state.get("html_content", ""),
        list_id=int(analysis.get("list_id") or 0),
        scheduled_at=state.get("scheduled_at"),
    )
    campaign_id = create_result.get("campaign_id")

    db_row: dict[str, Any] = {}
    if campaign_id:
        row = {
            "client_id": client.get("id"),
            "campaign_id_brevo": int(campaign_id),
            "subject": subject,
            "name": name,
            "list_id": int(analysis.get("list_id") or 0),
            "html_content": state.get("html_content", ""),
            "copy_variants": state.get("copy_variants", []),
            "briefing": state.get("briefing", {}),
            "analysis": analysis,
            "scheduled_at": state.get("scheduled_at"),
        }
        result = (
            supabase.table("email_campaigns")
            .upsert(row, on_conflict="campaign_id_brevo")
            .execute()
        )
        db_row = result.data[0] if result.data else {}

    log.info(
        "email.executor.done",
        campaign_id=campaign_id,
        db_row_id=db_row.get("id"),
        scheduled_at=state.get("scheduled_at"),
    )
    # silencia linter para tools registradas mas usadas só pela documentação do prompt
    _ = (create_brevo_campaign, send_brevo_campaign, save_email_campaign_row, _EXECUTOR_SYSTEM, user_prompt)

    return {
        "campaign_id": int(campaign_id) if campaign_id else None,
        "db_row_id": db_row.get("id"),
    }


# ===========================================================================
# NÓ 6: ANALISTA_DE_RESULTADOS
# ===========================================================================
_RESULTADOS_SYSTEM = """
Você é o ANALISTA_DE_RESULTADOS do Agente de Email Marketing.

Função: buscar métricas finais (~24h após disparo), persistir em email_campaigns
e gravar aprendizados em agent_memory.

Passos:
1. fetch_campaign_report(campaign_id) → métricas finais
2. update_email_campaign_report(campaign_id_brevo, report) → persiste em email_campaigns
3. save_email_memory para 1–2 aprendizados (memory_type: observation | pattern)

Heurísticas para gerar memória:
- open_rate >= 0.30 → "subject de [tipo] performa bem para vertical X"
- click_rate >= 0.05 → "CTA/hook funcionou — replicar"
- bounce_rate >= 0.05 → "lista precisa higienização"
- open_rate < baseline × 0.7 → "horário/segmento sub-ótimo"

Retorne EXCLUSIVAMENTE um JSON:
{
  "report": { ...resumo... },
  "memories_saved": 2,
  "verdict": "above_baseline|on_baseline|below_baseline"
}
""".strip()


async def analista_de_resultados_node(state: EmailAgentState) -> dict:
    campaign_id = state.get("campaign_id")
    client = state["client"]
    log.info("email.resultados.start", campaign_id=campaign_id)

    if not campaign_id:
        log.warning("email.resultados.skip_no_campaign_id")
        return {"report": {}}

    user_prompt = f"""
Cliente: {client.get("name")} ({client.get("vertical")})
Campaign ID Brevo: {campaign_id}
Analysis baseline:
{json.dumps(state.get("analysis", {}).get("baseline_metrics", {}), ensure_ascii=False)}
Subject usado: {state.get("analysis", {}).get("selected_subject")}

Execute os 3 passos e retorne o JSON.
""".strip()

    raw = await _agent_loop(
        tools=[fetch_campaign_report, update_email_campaign_report, save_email_memory],
        system_prompt=_RESULTADOS_SYSTEM,
        user_prompt=user_prompt,
        max_iterations=6,
    )

    parsed = _extract_json(raw)
    report = parsed.get("report") or {}

    log.info(
        "email.resultados.done",
        campaign_id=campaign_id,
        verdict=parsed.get("verdict"),
        memories_saved=parsed.get("memories_saved"),
    )
    return {"report": report}


# ===========================================================================
# Construção e compilação do grafo
# ===========================================================================
def build_email_graph() -> StateGraph:
    graph = StateGraph(EmailAgentState)

    graph.add_node("pesquisador", pesquisador_node)
    graph.add_node("analista_de_lista", analista_de_lista_node)
    graph.add_node("copywriter", copywriter_node)
    graph.add_node("otimizador", otimizador_node)
    graph.add_node("executor", executor_node)
    graph.add_node("analista_de_resultados", analista_de_resultados_node)

    graph.add_edge(START, "pesquisador")
    graph.add_edge("pesquisador", "analista_de_lista")
    graph.add_edge("analista_de_lista", "copywriter")
    graph.add_edge("copywriter", "otimizador")
    graph.add_edge("otimizador", "executor")
    graph.add_edge("executor", "analista_de_resultados")
    graph.add_edge("analista_de_resultados", END)

    return graph


compiled_email_graph = build_email_graph().compile()
