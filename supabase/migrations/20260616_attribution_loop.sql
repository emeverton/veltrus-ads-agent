-- =============================================================================
-- 20260616_attribution_loop.sql
-- Fecha a malha de atribuição CRM → campanha → receita real
-- =============================================================================

create extension if not exists "pgcrypto";

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references public.clients(id),
  campaign_id uuid references public.campaigns(id),
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
  lead_id uuid references public.leads(id),
  campaign_id uuid references public.campaigns(id),
  client_id uuid references public.clients(id),
  crm_deal_id text not null,
  revenue_amount decimal(10,2),
  currency text default 'BRL',
  closed_at timestamptz,
  created_at timestamptz default now()
);

create or replace view public.campaign_attribution
with (security_invoker = true) as
with lead_counts as (
  select
    campaign_id,
    count(distinct id) as leads_total
  from public.leads
  group by campaign_id
),
deal_totals as (
  select
    campaign_id,
    coalesce(sum(revenue_amount), 0) as revenue_closed,
    count(distinct id) as deals_closed
  from public.deals
  group by campaign_id
)
select
  c.id as campaign_id,
  c.campaign_id as external_campaign_id,
  c.name as campaign_name,
  c.platform,
  coalesce(dt.revenue_closed, 0) as revenue_closed,
  coalesce(lc.leads_total, 0) as leads_total,
  coalesce(dt.deals_closed, 0) as deals_closed
from public.campaigns c
left join lead_counts lc on lc.campaign_id = c.id
left join deal_totals dt on dt.campaign_id = c.id;

alter table public.leads enable row level security;
alter table public.deals enable row level security;

create index if not exists leads_campaign_idx on public.leads (campaign_id);
create index if not exists leads_crm_deal_idx on public.leads (crm_deal_id);
create index if not exists deals_campaign_idx on public.deals (campaign_id);
create index if not exists deals_crm_deal_idx on public.deals (crm_deal_id);

do $$
begin
  if not exists (
    select 1 from pg_trigger where tgname = 'leads_updated_at'
  ) then
    create trigger leads_updated_at
      before update on public.leads
      for each row execute function public.set_updated_at();
  end if;
end;
$$;
