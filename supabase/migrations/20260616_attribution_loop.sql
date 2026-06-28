-- =============================================================================
-- 20260616_attribution_loop.sql
-- Attribution Loop: leads/deals CRM + view operacional de atribuição.
-- BigQuery permanece como camada analítica; Supabase segue operacional.
-- =============================================================================

create extension if not exists "pgcrypto";

create table if not exists public.leads (
    id uuid primary key default gen_random_uuid(),
    client_id uuid references public.clients(id) on delete set null,
    campaign_id uuid references public.campaigns(id) on delete set null,
    external_campaign_id text,
    phone text,
    name text,
    crm_deal_id text,
    crm_status text,
    lead_source text default 'meta',
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists public.deals (
    id uuid primary key default gen_random_uuid(),
    lead_id uuid references public.leads(id) on delete set null,
    campaign_id uuid references public.campaigns(id) on delete set null,
    client_id uuid references public.clients(id) on delete set null,
    crm_deal_id text not null,
    revenue_amount decimal(10, 2),
    currency text default 'BRL',
    closed_at timestamptz,
    created_at timestamptz default now()
);

create or replace view public.campaign_attribution
with (security_invoker = true) as
select
    c.id as campaign_id,
    c.campaign_id as external_campaign_id,
    c.name as campaign_name,
    c.platform,
    coalesce(d.revenue_closed, 0) as revenue_closed,
    coalesce(l.leads_total, 0) as leads_total,
    coalesce(d.deals_closed, 0) as deals_closed
from public.campaigns c
left join (
    select
        campaign_id,
        count(distinct id) as leads_total
    from public.leads
    group by campaign_id
) l on l.campaign_id = c.id
left join (
    select
        campaign_id,
        sum(revenue_amount) as revenue_closed,
        count(distinct id) as deals_closed
    from public.deals
    group by campaign_id
) d on d.campaign_id = c.id;

alter table public.leads enable row level security;
alter table public.deals enable row level security;

drop trigger if exists leads_updated_at on public.leads;
create trigger leads_updated_at
    before update on public.leads
    for each row execute function public.set_updated_at();

create index if not exists leads_campaign_idx on public.leads (campaign_id, created_at desc);
create index if not exists leads_crm_deal_idx on public.leads (crm_deal_id);
create index if not exists deals_campaign_idx on public.deals (campaign_id, closed_at desc);
create index if not exists deals_crm_deal_idx on public.deals (crm_deal_id);
