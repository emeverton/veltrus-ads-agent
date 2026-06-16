-- =============================================================================
-- BigQuery Analytics Layer — veltrus-ads-agent
-- Dataset: veltrus_analytics (GCP project: veltrus-ads-agent)
-- Sync source: Supabase (scripts/sync_to_bigquery.py)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Base tables (mirror Supabase operational data)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `veltrus_analytics.campaigns` (
  id STRING NOT NULL,
  account_id STRING,
  campaign_id STRING,
  name STRING,
  platform STRING,
  status STRING,
  objective STRING,
  daily_budget FLOAT64,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  synced_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `veltrus_analytics.daily_metrics` (
  id STRING NOT NULL,
  campaign_id STRING NOT NULL,
  date DATE NOT NULL,
  spend FLOAT64,
  impressions INT64,
  clicks INT64,
  conversions FLOAT64,
  cpa FLOAT64,
  roas FLOAT64,
  ctr FLOAT64,
  attribution_window STRING,
  confidence_score FLOAT64,
  synced_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `veltrus_analytics.leads` (
  id STRING NOT NULL,
  client_id STRING,
  campaign_id STRING,
  external_campaign_id STRING,
  phone STRING,
  name STRING,
  crm_deal_id STRING,
  crm_status STRING,
  lead_source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  synced_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `veltrus_analytics.deals` (
  id STRING NOT NULL,
  lead_id STRING,
  campaign_id STRING,
  client_id STRING,
  crm_deal_id STRING NOT NULL,
  revenue_amount FLOAT64,
  currency STRING,
  closed_at TIMESTAMP,
  created_at TIMESTAMP,
  synced_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `veltrus_analytics.agent_decisions` (
  id STRING NOT NULL,
  campaign_id STRING NOT NULL,
  action_type STRING,
  reasoning STRING,
  payload JSON,
  executed BOOL,
  approved_by STRING,
  approved_at TIMESTAMP,
  created_at TIMESTAMP,
  synced_at TIMESTAMP NOT NULL
);

-- -----------------------------------------------------------------------------
-- Analytics views
-- -----------------------------------------------------------------------------

CREATE OR REPLACE VIEW `veltrus_analytics.campaign_attribution` AS
SELECT
  c.id AS campaign_id,
  c.campaign_id AS external_campaign_id,
  c.name AS campaign_name,
  c.platform,
  COALESCE(SUM(d.revenue_amount), 0) AS revenue_closed,
  COUNT(DISTINCT l.id) AS leads_total,
  COUNT(DISTINCT dl.id) AS deals_closed
FROM `veltrus_analytics.campaigns` c
LEFT JOIN `veltrus_analytics.leads` l ON l.campaign_id = c.id
LEFT JOIN `veltrus_analytics.deals` dl ON dl.campaign_id = c.id
GROUP BY c.id, c.campaign_id, c.name, c.platform;

CREATE OR REPLACE VIEW `veltrus_analytics.campaign_performance` AS
SELECT
  dm.campaign_id,
  c.name AS campaign_name,
  c.platform,
  dm.date,
  dm.spend,
  dm.impressions,
  dm.clicks,
  dm.conversions,
  dm.cpa,
  dm.roas AS roas_platform,
  dm.ctr,
  dm.attribution_window,
  dm.confidence_score,
  ca.revenue_closed,
  ca.leads_total,
  ca.deals_closed,
  SAFE_DIVIDE(ca.revenue_closed, dm.spend) AS roas_real
FROM `veltrus_analytics.daily_metrics` dm
JOIN `veltrus_analytics.campaigns` c ON c.id = dm.campaign_id
LEFT JOIN `veltrus_analytics.campaign_attribution` ca ON ca.campaign_id = dm.campaign_id;

CREATE OR REPLACE VIEW `veltrus_analytics.attribution_gap` AS
SELECT
  ca.campaign_id,
  ca.campaign_name,
  ca.platform,
  ca.revenue_closed,
  ca.leads_total,
  ca.deals_closed,
  SUM(dm.spend) AS spend_total,
  AVG(dm.roas) AS roas_platform_avg,
  SAFE_DIVIDE(ca.revenue_closed, SUM(dm.spend)) AS roas_real,
  SAFE_DIVIDE(ca.revenue_closed, SUM(dm.spend)) - AVG(dm.roas) AS roas_gap
FROM `veltrus_analytics.campaign_attribution` ca
LEFT JOIN `veltrus_analytics.daily_metrics` dm
  ON dm.campaign_id = ca.campaign_id
  AND dm.date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY
  ca.campaign_id,
  ca.campaign_name,
  ca.platform,
  ca.revenue_closed,
  ca.leads_total,
  ca.deals_closed;
