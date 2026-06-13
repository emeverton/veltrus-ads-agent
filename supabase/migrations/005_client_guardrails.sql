-- =============================================================================
-- 005_client_guardrails.sql
-- Guardrails por cliente + tabela agent_executions
-- =============================================================================

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS daily_budget_brl DECIMAL(10,2),
  ADD COLUMN IF NOT EXISTS max_budget_change_pct INTEGER DEFAULT 20,
  ADD COLUMN IF NOT EXISTS min_roas DECIMAL(5,2) DEFAULT 2.0,
  ADD COLUMN IF NOT EXISTS max_cpa_brl DECIMAL(10,2) DEFAULT 100.0,
  ADD COLUMN IF NOT EXISTS cycle_interval_minutes INTEGER DEFAULT 30,
  ADD COLUMN IF NOT EXISTS autonomous_mode BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS meta_ad_account_id TEXT,
  ADD COLUMN IF NOT EXISTS google_ads_customer_id TEXT;

COMMENT ON COLUMN public.clients.daily_budget_brl IS
  'Teto absoluto de gasto diário em BRL — nunca ultrapassar em ações do agente.';
COMMENT ON COLUMN public.clients.autonomous_mode IS
  'Se true, executa ações LOW sem aprovação humana para este cliente.';

CREATE TABLE IF NOT EXISTS public.agent_executions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_id UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  platform TEXT NOT NULL CHECK (platform IN ('meta', 'google', 'both')),
  cycle_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cycle_end TIMESTAMPTZ,
  actions_planned INTEGER NOT NULL DEFAULT 0,
  actions_approved INTEGER NOT NULL DEFAULT 0,
  actions_rejected INTEGER NOT NULL DEFAULT 0,
  actions_executed INTEGER NOT NULL DEFAULT 0,
  actions_detail JSONB NOT NULL DEFAULT '[]'::jsonb,
  budget_before_brl DECIMAL(10,2),
  budget_after_brl DECIMAL(10,2),
  status TEXT NOT NULL DEFAULT 'running' CHECK (
    status IN ('running', 'completed', 'failed', 'kill_switched')
  ),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.agent_executions IS
  'Auditoria de ciclos do agente por cliente — planejado, aprovado, rejeitado e executado.';

CREATE INDEX IF NOT EXISTS idx_agent_executions_client_id
  ON public.agent_executions(client_id);

CREATE INDEX IF NOT EXISTS idx_agent_executions_created_at
  ON public.agent_executions(created_at DESC);

ALTER TABLE public.agent_executions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on agent_executions"
  ON public.agent_executions
  FOR ALL
  USING (auth.role() = 'service_role');

GRANT ALL ON public.agent_executions TO service_role, authenticated, anon;

NOTIFY pgrst, 'reload schema';
