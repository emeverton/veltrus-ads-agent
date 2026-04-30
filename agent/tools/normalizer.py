"""
agent/tools/normalizer.py — Unified Marketing Schema

Normaliza raw_payloads da Meta Ads API e Google Ads API para um dict
padronizado que o agente usa para análise cross-platform.

=== Diferenças de Atribuição Entre Plataformas ===

META ADS
  Janela padrão: 7-day click + 1-day view.
  Uma conversão é contada se o usuário:
    (a) clicou no anúncio nos últimos 7 dias  → "7d_click"
    (b) visualizou o anúncio no último dia    → "1d_view"
  A API retorna a lista `actions` onde cada entrada tem:
    - "value":    total de conversões (click + view combinados)
    - "7d_click": conversões atribuídas a clique
    - "1d_view":  conversões atribuídas a visualização
  Este normalizer usa "7d_click" para conversions_click e "1d_view" para
  conversions_view quando disponíveis. Sem breakdown, estima 85/15 a partir
  do total "value" e reduz confidence_score para 0.75.
  Receita (action_values) não tem breakdown por janela na resposta padrão da API;
  o total de revenue é usado para roas_click.

GOOGLE ADS
  Atribuição padrão: Last Click, 30-day click + 1-day view (display/video).
    - metrics.conversions              → conversões click-based (cross-device)
    - metrics.view_through_conversions → conversões view-through (display/video)
    - metrics.conversions_value        → receita das conversões
  O modelo de atribuição (Last Click, Data-Driven, etc.) é configurado por
  conversion action, não por query — este normalizer não altera isso.
  Mapeia: conversions_click = metrics.conversions
          conversions_view  = metrics.view_through_conversions (se presente)

SUPABASE SEED DATA
  Dados gerados por scripts/seed_test_data.py não contêm breakdown de atribuição.
  confidence_score = 0.40 — o agente deve tratar anomalias deste nível com cautela.

=== Tiers de Confidence Score ===
  0.90–0.95: API real com breakdown completo de atribuição por janela
  0.75–0.85: API real sem breakdown (usando total de conversões)
  0.60–0.65: Linha do Supabase com raw_payload real mas pré-agregado
  0.40:      Seed / legacy — sem informação de atribuição confiável
"""
from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict

_CONVERSION_TYPES: frozenset[str] = frozenset(
    {"purchase", "lead", "complete_registration", "subscribe", "add_payment_info"}
)

# Janelas de atribuição canônicas
WINDOW_META_DEFAULT   = "7d_click_1d_view"
WINDOW_GOOGLE_DEFAULT = "30d_click_1d_view"
WINDOW_UNKNOWN        = "unknown"


# ---------------------------------------------------------------------------
# Schema unificado
# ---------------------------------------------------------------------------
class UnifiedMetrics(TypedDict):
    platform: str           # "meta" | "google" | "unknown"
    date: str               # "YYYY-MM-DD" ou "aggregated"
    data_source: str        # "meta_api" | "google_api" | "supabase" | "seed"

    spend_usd: float
    impressions: int
    clicks: int

    conversions_click: float   # atribuídas a clique
    conversions_view: float    # atribuídas a visualização
    revenue_usd: float

    cpa_click: float | None    # spend / conversions_click  (None se sem conversões)
    roas_click: float | None   # revenue / spend           (None se spend == 0)
    ctr: float                 # clicks / impressions

    attribution_window: str    # janela de atribuição detectada
    confidence_score: float    # 0.0–1.0


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _sum_by_window(actions: list[dict[str, Any]], types: frozenset[str], window: str) -> float:
    """Soma ações de tipos específicos para uma janela de atribuição."""
    return sum(
        float(a.get(window, 0))
        for a in actions
        if a.get("action_type") in types
    )


def _sum_total(actions: list[dict[str, Any]], types: frozenset[str]) -> float:
    """Soma total de ações (sem filtro de janela)."""
    return sum(
        float(a.get("value", 0))
        for a in actions
        if a.get("action_type") in types
    )


def _safe_cpa(spend: float, conversions: float) -> float | None:
    return round(spend / conversions, 4) if conversions > 0 else None


def _safe_roas(revenue: float, spend: float) -> float | None:
    return round(revenue / spend, 4) if spend > 0 else None


# ---------------------------------------------------------------------------
# 1. Normaliza raw_payload da Meta Ads API
# ---------------------------------------------------------------------------
def normalize_meta(raw_payload: dict[str, Any], date: str = "aggregated") -> UnifiedMetrics:
    """
    Normaliza o raw_payload retornado por meta_ads.get_campaign_insights().

    O payload é o objeto InsightData convertido em dict via dict(row).
    Campos esperados: spend, impressions, clicks, ctr, actions, action_values.
    """
    spend       = float(raw_payload.get("spend", 0) or 0)
    impressions = int(raw_payload.get("impressions", 0) or 0)
    clicks      = int(raw_payload.get("clicks", 0) or 0)
    ctr         = float(raw_payload.get("ctr", 0) or 0)

    actions       = raw_payload.get("actions", []) or []
    action_values = raw_payload.get("action_values", []) or []

    # Tenta extrair conversões com breakdown por janela
    conv_click = _sum_by_window(actions, _CONVERSION_TYPES, "7d_click")
    conv_view  = _sum_by_window(actions, _CONVERSION_TYPES, "1d_view")

    has_breakdown = (conv_click > 0 or conv_view > 0)

    if has_breakdown:
        confidence = 0.92
    else:
        # Sem breakdown: estima 85% click / 15% view a partir do total
        total_conv = _sum_total(actions, _CONVERSION_TYPES)
        conv_click = round(total_conv * 0.85, 4)
        conv_view  = round(total_conv * 0.15, 4)
        confidence = 0.75

    revenue = _sum_total(action_values, _CONVERSION_TYPES)

    # Se raw_payload é apenas o envelope resumido do nosso get_campaign_insights,
    # não o objeto InsightData completo
    if not actions and "conversions" in raw_payload:
        conv_click = float(raw_payload.get("conversions", 0) or 0) * 0.85
        conv_view  = float(raw_payload.get("conversions", 0) or 0) * 0.15
        revenue    = float(raw_payload.get("roas", 0) or 0) * spend
        confidence = 0.65

    return UnifiedMetrics(
        platform="meta",
        date=date,
        data_source="meta_api",
        spend_usd=round(spend, 4),
        impressions=impressions,
        clicks=clicks,
        conversions_click=round(conv_click, 4),
        conversions_view=round(conv_view, 4),
        revenue_usd=round(revenue, 4),
        cpa_click=_safe_cpa(spend, conv_click),
        roas_click=_safe_roas(revenue, spend),
        ctr=round(ctr, 6) if ctr else (round(clicks / impressions, 6) if impressions else 0.0),
        attribution_window=WINDOW_META_DEFAULT,
        confidence_score=confidence,
    )


# ---------------------------------------------------------------------------
# 2. Normaliza raw_payload da Google Ads API
# ---------------------------------------------------------------------------
def normalize_google(raw_payload: dict[str, Any], date: str = "aggregated") -> UnifiedMetrics:
    """
    Normaliza o raw_payload retornado por google_ads.get_campaign_insights().

    Estrutura esperada: {"cost_micros", "impressions", "clicks",
                          "conversions", "conversions_value", "row_count"}.
    view_through_conversions é opcional (presente apenas em campanhas display/video).
    """
    cost_micros = int(raw_payload.get("cost_micros", 0) or 0)
    spend       = cost_micros / 1_000_000
    impressions = int(raw_payload.get("impressions", 0) or 0)
    clicks      = int(raw_payload.get("clicks", 0) or 0)
    conv_click  = float(raw_payload.get("conversions", 0) or 0)
    conv_view   = float(raw_payload.get("view_through_conversions", 0) or 0)
    revenue     = float(raw_payload.get("conversions_value", 0) or 0)

    # Fallback: se spend já está em USD (payload resumido sem cost_micros)
    if cost_micros == 0 and "spend" in raw_payload:
        spend = float(raw_payload.get("spend", 0) or 0)

    ctr = round(clicks / impressions, 6) if impressions else 0.0

    # Google fornece conversões click-based por padrão; view_through é separado.
    # Sem breakdown de janela específico → confidence ligeiramente menor que Meta.
    confidence = 0.85 if conv_view == 0 else 0.88

    return UnifiedMetrics(
        platform="google",
        date=date,
        data_source="google_api",
        spend_usd=round(spend, 4),
        impressions=impressions,
        clicks=clicks,
        conversions_click=round(conv_click, 4),
        conversions_view=round(conv_view, 4),
        revenue_usd=round(revenue, 4),
        cpa_click=_safe_cpa(spend, conv_click),
        roas_click=_safe_roas(revenue, spend),
        ctr=ctr,
        attribution_window=WINDOW_GOOGLE_DEFAULT,
        confidence_score=confidence,
    )


# ---------------------------------------------------------------------------
# 3. Normaliza linha do Supabase daily_metrics
# ---------------------------------------------------------------------------
def normalize_supabase_row(row: dict[str, Any], platform: str) -> UnifiedMetrics:
    """
    Normaliza uma linha de daily_metrics do Supabase.

    Estratégia de detecção (em ordem de prioridade):
      1. raw_payload com estrutura Meta API (tem campo "actions") → normalize_meta
      2. raw_payload com estrutura Google API (tem "cost_micros") → normalize_google
      3. raw_payload de seed ("source": "seed_test_data") ou vazio → usa campos pré-computados

    Para dados de seed e legacy, conversions_view é estimada em 15% das conversões totais
    e confidence_score = 0.40.
    """
    raw: dict[str, Any] = row.get("raw_payload") or {}

    # --- Detecta se raw_payload contém dados reais de API ---
    if isinstance(raw.get("actions"), list):
        m = normalize_meta(raw, date=str(row.get("date", "aggregated")))
        # Rebaixa confidence se o dado vem do Supabase (pré-agregado)
        return {**m, "data_source": "supabase", "confidence_score": min(m["confidence_score"], 0.65)}

    if "cost_micros" in raw:
        g = normalize_google(raw, date=str(row.get("date", "aggregated")))
        return {**g, "data_source": "supabase", "confidence_score": min(g["confidence_score"], 0.65)}

    # --- Seed / legacy: usa campos pré-computados do banco ---
    spend       = float(row.get("spend", 0) or 0)
    impressions = int(row.get("impressions", 0) or 0)
    clicks      = int(row.get("clicks", 0) or 0)
    conversions = float(row.get("conversions", 0) or 0)
    roas        = float(row["roas"]) if row.get("roas") is not None else None
    cpa         = float(row["cpa"]) if row.get("cpa") is not None else None
    ctr         = float(row.get("ctr", 0) or 0)

    # Para seed: estima split 85% click / 15% view
    conv_click = round(conversions * 0.85, 4)
    conv_view  = round(conversions * 0.15, 4)
    revenue    = round(spend * roas, 4) if roas else 0.0

    # Usa attribution_window e confidence_score do banco se presentes (pós-migration)
    attr_window = row.get("attribution_window") or WINDOW_UNKNOWN
    confidence  = float(row.get("confidence_score") or 0.40)

    return UnifiedMetrics(
        platform=platform,
        date=str(row.get("date", "aggregated")),
        data_source="seed" if raw.get("source") == "seed_test_data" else "supabase",
        spend_usd=spend,
        impressions=impressions,
        clicks=clicks,
        conversions_click=conv_click,
        conversions_view=conv_view,
        revenue_usd=revenue,
        cpa_click=_safe_cpa(spend, conv_click) if cpa is None else round(cpa / 0.85, 4),
        roas_click=roas,
        ctr=ctr,
        attribution_window=attr_window,
        confidence_score=confidence,
    )


# ---------------------------------------------------------------------------
# 4. Normaliza o dict de saída de get_campaign_insights (Meta ou Google)
# ---------------------------------------------------------------------------
def normalize_insights(metrics: dict[str, Any], platform: str) -> UnifiedMetrics:
    """
    Normaliza o dict retornado por meta_ads.get_campaign_insights() ou
    google_ads.get_campaign_insights().

    Esses dicts têm a estrutura: {campaign_id, spend, impressions, ..., raw_payload}.
    Delega para normalize_meta ou normalize_google usando raw_payload quando disponível.
    """
    raw = metrics.get("raw_payload") or {}

    if platform == "meta":
        if raw and not raw.get("source"):
            return normalize_meta(raw, date=metrics.get("date", "aggregated"))
        # raw_payload ausente ou seed: usa campos do próprio dict
        return normalize_meta({
            "spend": metrics.get("spend", 0),
            "impressions": metrics.get("impressions", 0),
            "clicks": metrics.get("clicks", 0),
            "ctr": metrics.get("ctr", 0),
            "conversions": metrics.get("conversions", 0),
            "roas": metrics.get("roas"),
        }, date=metrics.get("date", "aggregated"))

    if platform == "google":
        if raw and "cost_micros" in raw:
            return normalize_google(raw, date=metrics.get("date", "aggregated"))
        return normalize_google({
            "spend": metrics.get("spend", 0),
            "impressions": metrics.get("impressions", 0),
            "clicks": metrics.get("clicks", 0),
            "conversions": metrics.get("conversions", 0),
            "conversions_value": (
                (metrics.get("roas") or 0) * (metrics.get("spend") or 0)
            ),
        }, date=metrics.get("date", "aggregated"))

    # Plataforma desconhecida: monta um UnifiedMetrics genérico
    spend       = float(metrics.get("spend", 0) or 0)
    impressions = int(metrics.get("impressions", 0) or 0)
    clicks      = int(metrics.get("clicks", 0) or 0)
    conversions = float(metrics.get("conversions", 0) or 0)
    roas        = metrics.get("roas")
    revenue     = round(spend * float(roas), 4) if roas else 0.0
    conv_click  = round(conversions * 0.85, 4)
    conv_view   = round(conversions * 0.15, 4)

    return UnifiedMetrics(
        platform=platform,
        date=metrics.get("date", "aggregated"),
        data_source="supabase",
        spend_usd=spend,
        impressions=impressions,
        clicks=clicks,
        conversions_click=conv_click,
        conversions_view=conv_view,
        revenue_usd=revenue,
        cpa_click=_safe_cpa(spend, conv_click),
        roas_click=float(roas) if roas else None,
        ctr=round(clicks / impressions, 6) if impressions else 0.0,
        attribution_window=WINDOW_UNKNOWN,
        confidence_score=0.50,
    )
