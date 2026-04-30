-- =============================================================================
-- 002_add_normalized_fields.sql
-- Adiciona campos de atribuição e confiança à tabela daily_metrics
-- Compatível com dados de seed já existentes (defaults conservadores)
-- =============================================================================

alter table public.daily_metrics
    add column if not exists attribution_window text    not null default 'unknown',
    add column if not exists confidence_score   numeric(4, 3) not null default 0.400;

comment on column public.daily_metrics.attribution_window is
    'Janela de atribuição dos dados: "7d_click_1d_view" (Meta padrão), '
    '"30d_click_1d_view" (Google padrão), "unknown" (seed/legacy).';

comment on column public.daily_metrics.confidence_score is
    'Qualidade dos dados: 0.90-0.95=API com breakdown completo, '
    '0.75-0.85=API sem breakdown, 0.60-0.65=Supabase com raw_payload real, '
    '0.40=seed/estimado.';

-- Dados de seed já inseridos recebem confidence_score=0.40 e window=unknown
-- pelo DEFAULT — nenhum UPDATE necessário.
