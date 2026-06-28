-- =============================================================================
-- 20260616_bigquery_analytics_layer.sql
-- View analitica para BigQuery: Ads spend + Attribution Loop CRM
-- =============================================================================

CREATE OR REPLACE VIEW public.campaign_attribution
WITH (security_invoker = true) AS
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

CREATE OR REPLACE VIEW public.analytics_campaign_daily
WITH (security_invoker = true) AS
SELECT
  concat(c.id::text, ':', dm.date::text) AS analytics_key,
  cl.id::text AS client_uuid,
  cl.name AS client_name,
  cl.vertical,
  aa.id::text AS ad_account_uuid,
  aa.account_id AS account_external_id,
  c.platform,
  c.id::text AS campaign_uuid,
  c.campaign_id AS external_campaign_id,
  c.name AS campaign_name,
  c.status,
  c.objective,
  dm.date,
  dm.spend::double precision AS spend_usd,
  dm.impressions,
  dm.clicks,
  dm.conversions::double precision AS conversions,
  dm.cpa::double precision AS cpa,
  dm.roas::double precision AS roas_platform,
  dm.ctr::double precision AS ctr,
  dm.attribution_window,
  dm.confidence_score::double precision AS confidence_score,
  COALESCE(ca.revenue_closed, 0)::double precision AS revenue_closed,
  COALESCE(ca.leads_total, 0)::bigint AS leads_total,
  COALESCE(ca.deals_closed, 0)::bigint AS deals_closed,
  CASE
    WHEN dm.spend > 0
      THEN round((COALESCE(ca.revenue_closed, 0) / dm.spend)::numeric, 4)::double precision
    ELSE NULL
  END AS roas_real,
  dm.created_at AS metric_created_at
FROM public.daily_metrics dm
JOIN public.campaigns c ON c.id = dm.campaign_id
JOIN public.ad_accounts aa ON aa.id = c.account_id
JOIN public.clients cl ON cl.id = aa.client_id
LEFT JOIN public.campaign_attribution ca ON ca.campaign_id = c.id;

COMMENT ON VIEW public.analytics_campaign_daily IS
  'Camada analitica diaria para BigQuery/BI: ads metrics + leads/deals/revenue real do CRM.';
