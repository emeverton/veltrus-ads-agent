-- Attribution Loop: fecha a malha de controle campaign_id → lead → deal → revenue real
-- Conecta campanhas de anúncios com leads do CRM e deals ganhos para calcular ROAS verdadeiro.

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
