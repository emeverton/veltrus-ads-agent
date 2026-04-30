-- =============================================================================
-- 003_kill_switch_log.sql
-- Tabela de auditoria do kill switch de segurança financeira
-- =============================================================================

create table public.kill_switch_log (
    id                   uuid        primary key default uuid_generate_v4(),
    account_external_id  text        not null,   -- ID externo da plataforma (act_xxx / customer_id)
    campaign_external_id text        not null,   -- ID externo da campanha
    campaign_name        text        not null,
    platform             text        not null check (platform in ('meta', 'google')),
    client_name          text,

    -- Qual regra disparou
    trigger_type  text not null check (
        trigger_type in ('spend_overage', 'cpa_spike', 'roas_critical')
    ),

    -- O que foi feito
    action_taken  text not null check (
        action_taken in ('paused', 'alerted', 'pause_failed', 'dry_run')
    ),

    trigger_value   numeric(12, 4) not null,   -- valor que disparou a regra
    threshold_value numeric(12, 4) not null,   -- limite que foi excedido

    resolved    boolean     not null default false,  -- marcado true após revisão humana
    notes       text,                               -- campo livre para o operador anotar
    created_at  timestamptz not null default now()
);

comment on table public.kill_switch_log is
    'Auditoria de todas as ações do kill switch de proteção financeira. '
    'Independente do LangGraph — gerado diretamente por scripts/kill_switch.py.';

comment on column public.kill_switch_log.trigger_type is
    'spend_overage: gasto > budget×1.1 | cpa_spike: CPA > cpa_max×2 | roas_critical: ROAS < 0.5';

comment on column public.kill_switch_log.action_taken is
    'paused: campanha pausada via API | alerted: apenas log/notificação | '
    'pause_failed: tentativa falhou | dry_run: modo simulação';

create index kill_switch_log_created_idx  on public.kill_switch_log (created_at desc);
create index kill_switch_log_resolved_idx on public.kill_switch_log (resolved, created_at desc);

alter table public.kill_switch_log enable row level security;

-- Acesso via service_role (kill_switch.py usa service_role_key)
grant all on public.kill_switch_log to service_role, authenticated, anon;

notify pgrst, 'reload schema';
