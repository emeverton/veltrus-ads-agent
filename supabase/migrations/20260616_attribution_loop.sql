-- =============================================================================
-- Migration: Attribution Loop — leads, deals, campaign_attribution view
-- Projeto: Veltrus Revenue OS
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Tabela: leads
-- Captura leads vindos de fontes externas (Meta, Google, Kommo CRM)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.leads (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id             UUID        REFERENCES public.clients(id),
  campaign_id           UUID        REFERENCES public.campaigns(id),
  external_campaign_id  TEXT,
  phone                 TEXT,
  name                  TEXT,
  crm_deal_id           TEXT,
  crm_status            TEXT,
  lead_source           TEXT        DEFAULT 'meta',
  created_at            TIMESTAMPTZ DEFAULT NOW(),
  updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_campaign_id   ON public.leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_leads_client_id     ON public.leads(client_id);
CREATE INDEX IF NOT EXISTS idx_leads_crm_deal_id   ON public.leads(crm_deal_id);
CREATE INDEX IF NOT EXISTS idx_leads_created_at    ON public.leads(created_at DESC);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE TRIGGER set_leads_updated_at
  BEFORE UPDATE ON public.leads
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Tabela: deals
-- Deals fechados sincronizados do Kommo CRM
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.deals (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id         UUID        REFERENCES public.leads(id),
  campaign_id     UUID        REFERENCES public.campaigns(id),
  client_id       UUID        REFERENCES public.clients(id),
  crm_deal_id     TEXT        NOT NULL,
  revenue_amount  DECIMAL(10,2),
  currency        TEXT        DEFAULT 'BRL',
  closed_at       TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deals_campaign_id  ON public.deals(campaign_id);
CREATE INDEX IF NOT EXISTS idx_deals_client_id    ON public.deals(client_id);
CREATE INDEX IF NOT EXISTS idx_deals_lead_id      ON public.deals(lead_id);
CREATE INDEX IF NOT EXISTS idx_deals_crm_deal_id  ON public.deals(crm_deal_id);
CREATE INDEX IF NOT EXISTS idx_deals_closed_at    ON public.deals(closed_at DESC);

-- ---------------------------------------------------------------------------
-- View: campaign_attribution
-- ROAS real baseado em deals CRM × spend das campanhas
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.campaign_attribution AS
SELECT
  c.id                          AS campaign_id,
  c.campaign_id                 AS external_campaign_id,
  c.name                        AS campaign_name,
  c.platform,
  COALESCE(SUM(d.revenue_amount), 0)  AS revenue_closed,
  COALESCE(COUNT(DISTINCT l.id), 0)   AS leads_total,
  COALESCE(COUNT(DISTINCT d.id), 0)   AS deals_closed
FROM public.campaigns c
LEFT JOIN public.leads  l ON l.campaign_id = c.id
LEFT JOIN public.deals  d ON d.campaign_id = c.id
GROUP BY c.id, c.campaign_id, c.name, c.platform;

-- ---------------------------------------------------------------------------
-- RLS: habilitar Row Level Security (acesso via service role key)
-- ---------------------------------------------------------------------------
ALTER TABLE public.leads  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.deals  ENABLE ROW LEVEL SECURITY;

-- Policies: service role bypassa RLS automaticamente
-- anon key sem policy = acesso negado (proteção adequada)
