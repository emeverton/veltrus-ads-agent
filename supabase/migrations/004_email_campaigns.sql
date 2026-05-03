-- =============================================================================
-- 004_email_campaigns.sql
-- Tabela de campanhas de email marketing (Brevo) gerenciadas pelo Agente de Email
-- =============================================================================

create table public.email_campaigns (
    id                  uuid        primary key default uuid_generate_v4(),
    client_id           uuid        not null references public.clients(id) on delete cascade,

    -- Identificação na plataforma externa (Brevo)
    campaign_id_brevo   bigint      not null unique,
    subject             text        not null,
    name                text,
    list_id             bigint,

    -- Métricas pós-disparo (preenchidas pelo ANALISTA_DE_RESULTADOS)
    sent                integer,
    delivered           integer,
    unique_opens        integer,
    unique_clicks       integer,
    open_rate           numeric(8, 6),
    click_rate          numeric(8, 6),
    bounce_rate         numeric(8, 6),
    unsubscribe_rate    numeric(8, 6),

    -- Conteúdo (auditoria)
    html_content        text,
    copy_variants       jsonb       not null default '[]'::jsonb,  -- subjects testados
    briefing            jsonb       not null default '{}'::jsonb,  -- pesquisa de mercado
    analysis            jsonb       not null default '{}'::jsonb,  -- horário/segmento

    -- Timing
    scheduled_at        timestamptz,
    sent_at             timestamptz,
    report_fetched_at   timestamptz,

    -- Auditoria
    raw_report          jsonb,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

comment on table public.email_campaigns is
    'Campanhas de email marketing criadas e disparadas via Brevo pelo Agente de Email. '
    'Métricas são populadas ~24h após envio pelo nó ANALISTA_DE_RESULTADOS.';

comment on column public.email_campaigns.campaign_id_brevo is
    'ID retornado por POST /emailCampaigns na API Brevo v3.';

comment on column public.email_campaigns.copy_variants is
    'Lista de subject lines geradas pelo COPYWRITER para A/B test ou histórico.';

create index email_campaigns_client_idx     on public.email_campaigns (client_id, created_at desc);
create index email_campaigns_sent_at_idx    on public.email_campaigns (sent_at desc);
create index email_campaigns_pending_report_idx
    on public.email_campaigns (sent_at)
    where report_fetched_at is null;

alter table public.email_campaigns enable row level security;
grant all on public.email_campaigns to service_role, authenticated, anon;

notify pgrst, 'reload schema';
