-- =============================================================================
-- 001_initial_schema.sql
-- Schema inicial do Veltrus Ads Agent
-- Toda comunicação via supabase-py (REST API) — sem conexão direta na 5432
-- =============================================================================

-- Extensões necessárias
create extension if not exists "uuid-ossp";
create extension if not exists "vector";          -- pgvector para embeddings

-- =============================================================================
-- 1. clients — clientes da Veltrus
-- =============================================================================
create table public.clients (
    id          uuid primary key default uuid_generate_v4(),
    name        text        not null,
    vertical    text        not null,               -- ex: "ecommerce", "saas", "retail"
    business_dna jsonb      not null default '{}',  -- dados de briefing, tom de voz, restrições
    active      boolean     not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

comment on table public.clients is 'Clientes da Veltrus que têm campanhas gerenciadas pelo agente.';
comment on column public.clients.business_dna is 'JSON livre com identidade de marca, restrições, objetivos e qualquer contexto relevante para o agente.';

-- =============================================================================
-- 2. ad_accounts — contas de ads vinculadas ao cliente
-- =============================================================================
create table public.ad_accounts (
    id          uuid primary key default uuid_generate_v4(),
    client_id   uuid        not null references public.clients(id) on delete cascade,
    platform    text        not null check (platform in ('meta', 'google')),
    account_id  text        not null,               -- ID externo da plataforma
    token       text,                               -- access token criptografado (nunca exposto via anon)
    active      boolean     not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (platform, account_id)
);

comment on column public.ad_accounts.token is 'Token de acesso renovável. Usar service_role key para leitura; jamais expor via anon key.';

-- =============================================================================
-- 3. campaigns — campanhas monitoradas
-- =============================================================================
create table public.campaigns (
    id           uuid primary key default uuid_generate_v4(),
    account_id   uuid        not null references public.ad_accounts(id) on delete cascade,
    campaign_id  text        not null,              -- ID externo na plataforma
    name         text        not null,
    platform     text        not null check (platform in ('meta', 'google')),
    status       text        not null default 'active' check (status in ('active', 'paused', 'archived')),
    objective    text,                              -- ex: "CONVERSIONS", "REACH"
    daily_budget numeric(12, 2),                   -- USD
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    unique (account_id, campaign_id)
);

-- =============================================================================
-- 4. daily_metrics — métricas diárias por campanha
-- =============================================================================
create table public.daily_metrics (
    id            uuid primary key default uuid_generate_v4(),
    campaign_id   uuid        not null references public.campaigns(id) on delete cascade,
    date          date        not null,
    spend         numeric(12, 4) not null default 0,   -- USD
    impressions   bigint        not null default 0,
    clicks        bigint        not null default 0,
    conversions   numeric(12, 4) not null default 0,
    cpa           numeric(12, 4),                      -- custo por aquisição (spend / conversions)
    roas          numeric(12, 4),                      -- retorno sobre gasto (revenue / spend)
    ctr           numeric(8, 6),                       -- taxa de clique (clicks / impressions)
    raw_payload   jsonb,                               -- payload original da API para auditoria
    created_at    timestamptz not null default now(),
    unique (campaign_id, date)
);

comment on column public.daily_metrics.raw_payload is 'Resposta bruta da API (Meta/Google) para facilitar reprocessamento sem nova chamada.';

-- =============================================================================
-- 5. agent_decisions — histórico de decisões do agente
-- =============================================================================
create table public.agent_decisions (
    id              uuid primary key default uuid_generate_v4(),
    campaign_id     uuid        not null references public.campaigns(id) on delete cascade,
    action_type     text        not null,            -- ex: "budget_increase", "pause_adset", "bid_adjustment"
    reasoning       text        not null,            -- raciocínio do agente (chain-of-thought)
    payload         jsonb       not null default '{}', -- parâmetros da ação executada/proposta
    executed        boolean     not null default false,
    approved_by     text,                            -- email ou "autonomous" se AGENT_AUTONOMOUS_MODE=true
    approved_at     timestamptz,
    created_at      timestamptz not null default now()
);

comment on column public.agent_decisions.reasoning is 'Raciocínio completo do LLM antes de tomar a decisão, para auditoria e fine-tuning.';
comment on column public.agent_decisions.approved_by is 'Identificação de quem aprovou a ação. "autonomous" indica execução sem revisão humana.';

-- =============================================================================
-- 6. agent_memory — memória semântica do agente (pgvector)
-- =============================================================================
create table public.agent_memory (
    id           uuid primary key default uuid_generate_v4(),
    campaign_id  uuid        references public.campaigns(id) on delete cascade,
    content      text        not null,              -- texto da memória (observação, padrão, insight)
    embedding    vector(1536),                      -- embedding OpenAI/Anthropic (dimensão 1536)
    memory_type  text        not null default 'observation' check (
                     memory_type in ('observation', 'pattern', 'rule', 'context')
                 ),
    created_at   timestamptz not null default now()
);

comment on table public.agent_memory is 'Memória semântica persistente do agente. Buscada via similarity search (pgvector) a cada ciclo.';
comment on column public.agent_memory.campaign_id is 'Null = memória global; preenchido = memória específica da campanha.';

-- Índice HNSW para similarity search eficiente
create index agent_memory_embedding_idx
    on public.agent_memory
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

-- =============================================================================
-- Timestamps automáticos via trigger
-- =============================================================================
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger clients_updated_at
    before update on public.clients
    for each row execute function public.set_updated_at();

create trigger ad_accounts_updated_at
    before update on public.ad_accounts
    for each row execute function public.set_updated_at();

create trigger campaigns_updated_at
    before update on public.campaigns
    for each row execute function public.set_updated_at();

-- =============================================================================
-- Row Level Security
-- Todas as tabelas bloqueadas por padrão; acesso liberado somente via service_role
-- (o agente usa SUPABASE_SERVICE_ROLE_KEY, que bypassa RLS)
-- =============================================================================
alter table public.clients         enable row level security;
alter table public.ad_accounts     enable row level security;
alter table public.campaigns       enable row level security;
alter table public.daily_metrics   enable row level security;
alter table public.agent_decisions enable row level security;
alter table public.agent_memory    enable row level security;

-- Bloqueia acesso anônimo em todas as tabelas (deny-by-default)
-- O dashboard Next.js usa o anon key somente para dados de leitura autorizados.
-- Adicionar políticas de leitura por autenticação quando o módulo de auth for implementado.

-- =============================================================================
-- Índices auxiliares para queries frequentes do agente
-- =============================================================================
create index daily_metrics_campaign_date_idx on public.daily_metrics (campaign_id, date desc);
create index agent_decisions_campaign_idx    on public.agent_decisions (campaign_id, created_at desc);
create index campaigns_account_status_idx   on public.campaigns (account_id, status);
