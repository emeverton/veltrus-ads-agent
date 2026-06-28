-- =============================================================================
-- 20260616_attribution_loop.sql
-- Attribution loop: campaign → lead → deal → revenue real → ROAS verdadeiro
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID REFERENCES public.clients(id),
  campaign_id UUID REFERENCES public.campaigns(id),
  external_campaign_id TEXT,
  phone TEXT,
  name TEXT,
  crm_deal_id TEXT,
  crm_status TEXT,
  lead_source TEXT DEFAULT 'meta',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.deals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID REFERENCES public.leads(id),
  campaign_id UUID REFERENCES public.campaigns(id),
  client_id UUID REFERENCES public.clients(id),
  crm_deal_id TEXT NOT NULL,
  revenue_amount DECIMAL(10,2),
  currency TEXT DEFAULT 'BRL',
  closed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE VIEW public.campaign_attribution AS
SELECT
  c.id AS campaign_id,
  c.campaign_id AS external_campaign_id,
  c.name AS campaign_name,
  c.platform,
  COALESCE(SUM(d.revenue_amount), 0) AS revenue_closed,
  COALESCE(COUNT(DISTINCT l.id), 0) AS leads_total,
  COALESCE(COUNT(DISTINCT d.id), 0) AS deals_closed
FROM public.campaigns c
LEFT JOIN public.leads l ON l.campaign_id = c.id
LEFT JOIN public.deals d ON d.campaign_id = c.id
GROUP BY c.id, c.campaign_id, c.name, c.platform;

-- RLS (mesmo padrão das demais tabelas — acesso via service_role)
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.deals ENABLE ROW LEVEL SECURITY;

-- Índices para lookups do attribution loop
CREATE INDEX IF NOT EXISTS leads_crm_deal_id_idx ON public.leads (crm_deal_id);
CREATE INDEX IF NOT EXISTS leads_campaign_id_idx ON public.leads (campaign_id);
CREATE INDEX IF NOT EXISTS deals_campaign_id_idx ON public.deals (campaign_id);
CREATE INDEX IF NOT EXISTS deals_crm_deal_id_idx ON public.deals (crm_deal_id);

CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON public.leads
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
