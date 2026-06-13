# Veltrus Ads Agent — Documentação Completa do Projeto

> Gerado automaticamente em **2026-06-13 11:10 UTC** pelo plugin `scripts/export_bundle.py`

---

## Índice

1. [Visão Geral](#visão-geral)
2. [Stack Tecnológica](#stack-tecnológica)
3. [Arquitetura do Sistema](#arquitetura-do-sistema)
4. [Agente de Ads (LangGraph)](#agente-de-ads-langgraph)
5. [Agente de Email (Brevo)](#agente-de-email-brevo)
6. [API FastAPI](#api-fastapi)
7. [Banco de Dados (Supabase)](#banco-de-dados-supabase)
8. [Aprovação Humana e WhatsApp](#aprovação-humana-e-whatsapp)
9. [Kill Switch](#kill-switch)
10. [Deploy e Infraestrutura](#deploy-e-infraestrutura)
11. [Variáveis de Ambiente](#variáveis-de-ambiente)
12. [Setup e Execução](#setup-e-execução)
13. [Inventário de Arquivos](#inventário-de-arquivos)

---

## Visão Geral

O **Veltrus Ads Agent** é um sistema multi-agente autônomo que monitora,
analisa e otimiza campanhas de anúncios em **Meta Ads** e **Google Ads**.
Inclui também um agente de **email marketing** integrado ao **Brevo**.

### Funcionalidades implementadas

| Feature | Status | Arquivo principal |
|---------|--------|-------------------|
| Agente de Ads (LangGraph) | ✅ Implementado | `agent/graph.py` |
| Agente de Email (Brevo) | ✅ Implementado | `agent/email_graph.py` |
| API de decisões (aprovação humana) | ✅ Implementado | `api/routers/decisions.py` |
| Trigger manual do agente | ✅ Implementado | `api/routers/run.py` |
| Trigger email marketing | ✅ Implementado | `api/routers/run_email.py` |
| Integração Meta Ads API | ✅ Implementado | `agent/tools/meta_ads.py` |
| Integração Google Ads API | ✅ Implementado | `agent/tools/google_ads.py` |
| Integração Brevo API | ✅ Implementado | `agent/tools/email_brevo.py` |
| Memória persistente (Supabase) | ✅ Implementado | `agent/tools/supabase_client.py` |
| Normalizador de métricas | ✅ Implementado | `agent/tools/normalizer.py` |
| Kill Switch (proteção financeira) | ✅ Implementado | `scripts/kill_switch.py` |
| Agendamento APScheduler | ✅ Implementado | `agent/main.py` |
| Docker Compose (api + agent + caddy) | ✅ Implementado | `docker-compose.yml` |
| Notificação n8n/WhatsApp | ✅ Implementado | `agent/graph.py` → `notify_human` |
| Dashboard Next.js | 🔶 Scaffold | `dashboard/` |

### Versão exportada

- **Commit:** `459ae456bfd79dfd6c5ba756f5927e862a0b9231`
- **Branch:** `cursor/export-bundle-plugin-b4be`
- **Data:** 2026-06-13 11:10:27 +0000
- **Mensagem:** feat: add export bundle plugin with full project documentation

---

## Stack Tecnológica

| Camada | Tecnologia | Versão/Ferramenta |
|--------|------------|-------------------|
| Agente | Python + LangGraph | Python 3.12 |
| LLM | Anthropic Claude | claude-sonnet-4-6 |
| API | FastAPI + Uvicorn | REST |
| Banco | Supabase (Postgres) | pgvector |
| Frontend | Next.js 14 + Tailwind | App Router |
| Agendamento | APScheduler | BlockingScheduler |
| Deploy | Docker + Caddy | TLS automático |
| Email | Brevo API v3 | REST |

---

## Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────────┐
│                    Dashboard (Next.js)                      │
│              Visualização · Configuração · Alertas          │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────┐
│                        API (FastAPI)                        │
│     /decisions · /run · /run-email · /health                │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Agente (LangGraph)                        │
│  Ads Graph: analista → estrategista → revisor → executor    │
│  Email Graph: pesquisador → copywriter → executor → ...     │
└───────┬───────────────────────┬─────────────────────────────┘
        │                       │
┌───────▼──────┐    ┌───────────▼──────────────────────────┐
│  Supabase    │    │         APIs Externas                 │
│  · Database  │    │  · Meta Marketing API                 │
│  · Memória   │    │  · Google Ads API                    │
│  · Decisões  │    │  · Anthropic API (Claude)            │
└──────────────┘    │  · Brevo API (email)                 │
                    └──────────────────────────────────────┘
```

---

## Agente de Ads (LangGraph)

**Arquivo:** `agent/graph.py`

### Fluxo do grafo

```
START → analista ─(anomalias?)→ estrategista → revisor → executor → memorizador → END
                └─(sem anomalias)──────────────────────────────→ memorizador → END
```

### Nós

| Nó | Função |
|----|--------|
| `analista` | Busca métricas 7 dias, detecta anomalias (CPA spike, ROAS < 1, CTR drop) |
| `estrategista` | Define ação: budget_increase/decrease, pause/activate, monitor_only |
| `revisor` | Classifica risco: LOW / MEDIUM / HIGH |
| `executor` | Salva decisão, executa via API ou enfileira aprovação humana |
| `memorizador` | Grava 1-3 insights em `agent_memory` |

### Ferramentas (tools)

| Tool | Descrição |
|------|-----------|
| `fetch_account_campaigns` | Campanhas do Supabase |
| `fetch_daily_metrics` | Métricas normalizadas |
| `fetch_meta_campaigns_live` | Campanhas Meta em tempo real |
| `fetch_meta_insights_live` | Insights Meta em tempo real |
| `search_agent_memory` | Busca textual em memória |
| `save_decision` | Insere em `agent_decisions` |
| `run_meta_action` | pause / activate / budget via Meta |
| `run_google_action` | pause / activate / budget via Google |
| `notify_human` | POST para n8n webhook |
| `save_memory` | Insere em `agent_memory` |

### Regras de execução

| Risco | AGENT_AUTONOMOUS_MODE=true | AGENT_AUTONOMOUS_MODE=false |
|-------|---------------------------|----------------------------|
| LOW | Executa automaticamente | Enfileira aprovação humana |
| MEDIUM | Enfileira aprovação humana | Enfileira aprovação humana |
| HIGH | Enfileira aprovação humana | Enfileira aprovação humana |

### Entrypoints

| Arquivo | Função |
|---------|--------|
| `agent/run.py` | `run_all_accounts()` — executa grafo para cada conta ativa |
| `agent/main.py` | APScheduler — ciclo a cada `AGENT_CYCLE_INTERVAL_MINUTES` |

---

## Agente de Email (Brevo)

**Arquivo:** `agent/email_graph.py`

### Fluxo do grafo

```
START → pesquisador → analista_de_lista → copywriter → otimizador
      → executor → analista_de_resultados → END
```

### Nós

| Nó | Função |
|----|--------|
| `pesquisador` | Web search (Anthropic) para mercado/concorrentes/tendências |
| `analista_de_lista` | Listas Brevo, campanhas recentes, melhor horário |
| `copywriter` | 3 variantes de assunto + corpo HTML |
| `otimizador` | Calcula `scheduled_at` (ISO UTC) |
| `executor` | Cria campanha Brevo + upsert `email_campaigns` |
| `analista_de_resultados` | Busca relatório, atualiza DB, salva memórias |

### Trigger via API

```bash
curl -X POST http://localhost:8000/run-email \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"client_id": "uuid", "list_id": 1, "context": "Black Friday"}'
```

---

## API FastAPI

**Arquivo:** `api/main.py`

### Endpoints implementados

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| `GET` | `/health` | — | Health check |
| `GET` | `/decisions` | X-API-Key | Lista decisões pendentes |
| `PATCH` | `/decisions/{id}/approve` | X-API-Key | Aprova e executa ação |
| `PATCH` | `/decisions/{id}/reject` | X-API-Key | Rejeita com motivo |
| `POST` | `/run` | X-API-Key | Dispara ciclo do agente em background |
| `POST` | `/run-email` | X-API-Key | Dispara agente de email em background |

### Autenticação

Todos os endpoints (exceto `/health`) requerem header:
```
X-API-Key: {API_SECRET_KEY}
```

### Documentação interativa

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Banco de Dados (Supabase)

### Migrations

| Arquivo | Conteúdo |
|---------|----------|
| `001_initial_schema.sql` | clients, ad_accounts, campaigns, daily_metrics, agent_decisions, agent_memory |
| `002_add_normalized_fields.sql` | attribution_window, confidence_score em daily_metrics |
| `003_kill_switch_log.sql` | Tabela kill_switch_log (auditoria) |
| `004_email_campaigns.sql` | Tabela email_campaigns (Brevo) |

### Tabelas principais

| Tabela | Propósito |
|--------|-----------|
| `clients` | Clientes Veltrus (name, vertical, business_dna) |
| `ad_accounts` | Contas Meta/Google vinculadas |
| `campaigns` | Campanhas monitoradas |
| `daily_metrics` | Métricas diárias (spend, cpa, roas, ctr) |
| `agent_decisions` | Decisões do agente (ação, reasoning, executed) |
| `agent_memory` | Memória persistente (content, embedding vector) |
| `kill_switch_log` | Log do kill switch |
| `email_campaigns` | Campanhas de email (Brevo) |

---

## Aprovação Humana e WhatsApp

### Fluxo completo

```
Agente LangGraph
  └─ executor (risco MEDIUM/HIGH ou autonomous=false)
       └─ save_decision(executed=false)
       └─ notify_human()
            └─ POST → N8N_WEBHOOK_URL
                     │
               ┌─────▼─────────────────────────────┐
               │  n8n Workflow                        │
               │  1. Webhook (trigger)                │
               │  2. WhatsApp Business API (botões)   │
               │  3. Webhook (resposta do usuário)    │
               │  4. PATCH /decisions/{id}/approve    │
               │     ou /decisions/{id}/reject        │
               └─────────────────────────────────────┘
```

### Payload enviado ao n8n

```json
{
  "decision_id": "uuid",
  "campaign_name": "Campanha Black Friday",
  "action_type": "budget_increase",
  "risk_level": "MEDIUM",
  "reasoning": "ROAS 3.8x acima da meta...",
  "phone_number": "5511999998888"
}
```

### Estados de uma decisão

| executed | approved_at | Significado |
|----------|-------------|-------------|
| false | null | ⏳ Pendente |
| true | preenchido | ✅ Aprovada e executada |
| false | preenchido | ❌ Rejeitada |

---

## Kill Switch

**Arquivo:** `scripts/kill_switch.py`

Script de segurança **independente do agente** — roda via cron a cada hora.

| Regra | Condição | Ação |
|-------|----------|------|
| `spend_overage` | gasto hoje > daily_budget × 1.1 | Pausa campanha |
| `cpa_spike` | CPA hoje > cpa_max × 2.0 | Pausa campanha |
| `roas_critical` | ROAS hoje < 0.5 | Alerta (sem pausa) |

```bash
# Execução manual
PYTHONPATH=. python scripts/kill_switch.py

# Simulação (dry-run)
PYTHONPATH=. python scripts/kill_switch.py --dry-run
```

---

## Deploy e Infraestrutura

### Docker Compose

| Serviço | Comando | Porta |
|---------|---------|-------|
| `api` | uvicorn api.main:app --workers 2 | 8000 (interno) |
| `agent` | python -m agent.main | — |
| `caddy` | Reverse proxy + TLS | 80, 443 |

### Scripts de deploy

| Script | Função |
|--------|--------|
| `scripts/setup.sh` | Bootstrap VPS (Docker, compose) |
| `scripts/deploy.sh` | git pull + docker compose up |
| `scripts/remote_deploy.sh` | rsync + SSH deploy |
| `scripts/seed_test_data.py` | Dados de teste para dev |

### Railway

- `Procfile` — uvicorn na porta `$PORT`
- `railway.json` — Nixpacks build, healthcheck `/health`

---

## Variáveis de Ambiente

Veja `.env.example` para a lista completa. Principais:

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | ✅ | Chave da API Anthropic |
| `SUPABASE_URL` | ✅ | URL do projeto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Chave service_role |
| `API_SECRET_KEY` | ✅ | Chave de autenticação da API |
| `META_ACCESS_TOKEN` | — | Token Meta Ads |
| `GOOGLE_ADS_*` | — | Credenciais Google Ads |
| `BREVO_API_KEY` | — | Chave Brevo (email) |
| `AGENT_AUTONOMOUS_MODE` | — | false = somente leitura (padrão) |
| `N8N_WEBHOOK_URL` | — | Webhook n8n para WhatsApp |

---

## Setup e Execução

```bash
# 1. Configurar ambiente
cp .env.example .env
# Preencher todas as variáveis

# 2. Backend Python
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Aplicar migrations no Supabase
# (via Supabase CLI ou dashboard SQL editor)

# 4. Iniciar API
PYTHONPATH=. uvicorn api.main:app --reload --port 8000

# 5. Iniciar agente (ciclo agendado)
PYTHONPATH=. python -m agent.main

# 6. Ou disparar manualmente
curl -X POST http://localhost:8000/run -H "X-API-Key: $API_SECRET_KEY"
```

---

## Inventário de Arquivos

Total de arquivos no pacote: **81**
Arquivos Python com código: **17**
Migrations SQL: **5**

### Estrutura de pastas

```
./
  ├── .dockerignore (249 bytes)
  ├── .env.example (3,627 bytes)
  ├── .env.railway.example (671 bytes)
  ├── .gitignore (483 bytes)
  ├── CLAUDE.md (3,568 bytes)
  ├── Caddyfile (1,043 bytes)
  ├── Dockerfile (1,359 bytes)
  ├── Procfile (66 bytes)
  ├── README.md (15,496 bytes)
  ├── docker-compose.yml (1,983 bytes)
  ├── railway.json (398 bytes)
  ├── requirements.txt (746 bytes)
  ├── runtime.txt (12 bytes)
agent/
  ├── __init__.py (0 bytes)
  ├── config.py (1,634 bytes (55 linhas))
  ├── email_graph.py (26,451 bytes (751 linhas))
  ├── graph.py (29,972 bytes (833 linhas))
  ├── __init__.py (0 bytes)
  ├── campaign_manager.py (0 bytes)
  ├── google_agent.py (0 bytes)
  ├── meta_agent.py (0 bytes)
  ├── main.py (1,440 bytes (57 linhas))
  ├── __init__.py (0 bytes)
  ├── store.py (0 bytes)
  ├── __init__.py (0 bytes)
  ├── analyzer.py (0 bytes)
  ├── executor.py (0 bytes)
  ├── optimizer.py (0 bytes)
  ├── reporter.py (0 bytes)
  ├── __init__.py (0 bytes)
  ├── templates.py (0 bytes)
  ├── run.py (2,689 bytes (94 linhas))
  ├── __init__.py (0 bytes)
  ├── email_brevo.py (18,857 bytes (556 linhas))
  ├── google_ads.py (11,028 bytes (310 linhas))
  ├── meta_ads.py (9,735 bytes (294 linhas))
  ├── normalizer.py (14,875 bytes (347 linhas))
  ├── supabase_client.py (608 bytes (18 linhas))
api/
  ├── __init__.py (0 bytes)
  ├── dependencies.py (0 bytes)
  ├── main.py (1,967 bytes (58 linhas))
  ├── __init__.py (0 bytes)
  ├── schemas.py (0 bytes)
  ├── __init__.py (0 bytes)
  ├── agents.py (0 bytes)
  ├── analytics.py (0 bytes)
  ├── campaigns.py (0 bytes)
  ├── decisions.py (11,015 bytes (306 linhas))
  ├── run.py (1,095 bytes (37 linhas))
  ├── run_email.py (3,147 bytes (105 linhas))
  ├── webhooks.py (0 bytes)
dashboard/
  ├── page.tsx (0 bytes)
  ├── page.tsx (0 bytes)
  ├── layout.tsx (0 bytes)
  ├── page.tsx (0 bytes)
  ├── page.tsx (0 bytes)
  ├── api.ts (0 bytes)
  ├── utils.ts (0 bytes)
  ├── next.config.js (0 bytes)
  ├── package.json (1,674 bytes)
  ├── tailwind.config.ts (0 bytes)
  ├── tsconfig.json (0 bytes)
  ├── index.ts (0 bytes)
docs/
  ├── PROJETO_COMPLETO.md (21,989 bytes)
  ├── api.md (0 bytes)
  ├── architecture.md (0 bytes)
scripts/
  ├── deploy.sh (1,559 bytes)
  ├── export_bundle.py (26,624 bytes (671 linhas))
  ├── kill_switch.py (12,697 bytes (366 linhas))
  ├── remote_deploy.sh (2,272 bytes)
  ├── seed_test_data.py (7,135 bytes (217 linhas))
  ├── setup.sh (1,429 bytes)
supabase/
  ├── 001_initial_schema.sql (9,448 bytes)
  ├── 002_add_normalized_fields.sql (1,108 bytes)
  ├── 003_kill_switch_log.sql (2,373 bytes)
  ├── 004_email_campaigns.sql (2,643 bytes)
  ├── seed.sql (0 bytes)
tests/
  ├── __init__.py (0 bytes)
  ├── __init__.py (0 bytes)
  ├── __init__.py (0 bytes)
  ├── __init__.py (0 bytes)
```

### Manifesto completo

| Arquivo | Tamanho | SHA256 (16) |
|---------|---------|-------------|
| `.dockerignore` | 249 | `6619e4d28653b23a` |
| `.env.example` | 3,627 | `26fbe50488628740` |
| `.env.railway.example` | 671 | `81ff3d0d73464c3f` |
| `.gitignore` | 483 | `39f3f7b90fcaa6d0` |
| `CLAUDE.md` | 3,568 | `4e287d88cb0a284d` |
| `Caddyfile` | 1,043 | `a51187208bcb4dc7` |
| `Dockerfile` | 1,359 | `0cb501ec97d13950` |
| `Procfile` | 66 | `1eb9d6e077f26af8` |
| `README.md` | 15,496 | `1046cdef481e3af9` |
| `agent/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `agent/config.py` | 1,634 | `9d16bd1bae699c52` |
| `agent/email_graph.py` | 26,451 | `1df12363ad438cae` |
| `agent/graph.py` | 29,972 | `66c4b6365e420c98` |
| `agent/graphs/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `agent/graphs/campaign_manager.py` | 0 | `e3b0c44298fc1c14` |
| `agent/graphs/google_agent.py` | 0 | `e3b0c44298fc1c14` |
| `agent/graphs/meta_agent.py` | 0 | `e3b0c44298fc1c14` |
| `agent/main.py` | 1,440 | `4fd1dd14fcab9075` |
| `agent/memory/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `agent/memory/store.py` | 0 | `e3b0c44298fc1c14` |
| `agent/nodes/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `agent/nodes/analyzer.py` | 0 | `e3b0c44298fc1c14` |
| `agent/nodes/executor.py` | 0 | `e3b0c44298fc1c14` |
| `agent/nodes/optimizer.py` | 0 | `e3b0c44298fc1c14` |
| `agent/nodes/reporter.py` | 0 | `e3b0c44298fc1c14` |
| `agent/prompts/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `agent/prompts/templates.py` | 0 | `e3b0c44298fc1c14` |
| `agent/run.py` | 2,689 | `18de6ddf92ff4989` |
| `agent/tools/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `agent/tools/email_brevo.py` | 18,857 | `dc51121a1b1817d1` |
| `agent/tools/google_ads.py` | 11,028 | `76e718b54655d695` |
| `agent/tools/meta_ads.py` | 9,735 | `ee8674dbbc439943` |
| `agent/tools/normalizer.py` | 14,875 | `0a3e17a17e00289b` |
| `agent/tools/supabase_client.py` | 608 | `411eb41b8b20e353` |
| `api/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `api/dependencies.py` | 0 | `e3b0c44298fc1c14` |
| `api/main.py` | 1,967 | `91481b9eec71907c` |
| `api/models/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `api/models/schemas.py` | 0 | `e3b0c44298fc1c14` |
| `api/routers/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `api/routers/agents.py` | 0 | `e3b0c44298fc1c14` |
| `api/routers/analytics.py` | 0 | `e3b0c44298fc1c14` |
| `api/routers/campaigns.py` | 0 | `e3b0c44298fc1c14` |
| `api/routers/decisions.py` | 11,015 | `99c8071932fc5995` |
| `api/routers/run.py` | 1,095 | `c4de403edac1731a` |
| `api/routers/run_email.py` | 3,147 | `72dc6c8f3c93434f` |
| `api/routers/webhooks.py` | 0 | `e3b0c44298fc1c14` |
| `dashboard/app/analytics/page.tsx` | 0 | `e3b0c44298fc1c14` |
| `dashboard/app/campaigns/page.tsx` | 0 | `e3b0c44298fc1c14` |
| `dashboard/app/layout.tsx` | 0 | `e3b0c44298fc1c14` |
| `dashboard/app/page.tsx` | 0 | `e3b0c44298fc1c14` |
| `dashboard/app/settings/page.tsx` | 0 | `e3b0c44298fc1c14` |
| `dashboard/lib/api.ts` | 0 | `e3b0c44298fc1c14` |
| `dashboard/lib/utils.ts` | 0 | `e3b0c44298fc1c14` |
| `dashboard/next.config.js` | 0 | `e3b0c44298fc1c14` |
| `dashboard/package.json` | 1,674 | `82a43e42bfc97d23` |
| `dashboard/tailwind.config.ts` | 0 | `e3b0c44298fc1c14` |
| `dashboard/tsconfig.json` | 0 | `e3b0c44298fc1c14` |
| `dashboard/types/index.ts` | 0 | `e3b0c44298fc1c14` |
| `docker-compose.yml` | 1,983 | `649e3815d64ce00e` |
| `docs/PROJETO_COMPLETO.md` | 21,989 | `28d1ea158618636a` |
| `docs/api.md` | 0 | `e3b0c44298fc1c14` |
| `docs/architecture.md` | 0 | `e3b0c44298fc1c14` |
| `railway.json` | 398 | `e64a82ccdb8c41b1` |
| `requirements.txt` | 746 | `b8b6d99f92af1174` |
| `runtime.txt` | 12 | `0ecb97b647d70ee7` |
| `scripts/deploy.sh` | 1,559 | `2b5ed97501bb7963` |
| `scripts/export_bundle.py` | 26,624 | `dac6dc35be49dd26` |
| `scripts/kill_switch.py` | 12,697 | `6c3dba7f3e24a0c5` |
| `scripts/remote_deploy.sh` | 2,272 | `0c6519e039081f2e` |
| `scripts/seed_test_data.py` | 7,135 | `8b74feb4c6563a49` |
| `scripts/setup.sh` | 1,429 | `aa2c7f9586319057` |
| `supabase/migrations/001_initial_schema.sql` | 9,448 | `72e3e45549049f55` |
| `supabase/migrations/002_add_normalized_fields.sql` | 1,108 | `911988e0329c5ac7` |
| `supabase/migrations/003_kill_switch_log.sql` | 2,373 | `20c881a79617f348` |
| `supabase/migrations/004_email_campaigns.sql` | 2,643 | `6f59bab481ec5d11` |
| `supabase/seed.sql` | 0 | `e3b0c44298fc1c14` |
| `tests/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `tests/agent/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `tests/api/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `tests/integration/__init__.py` | 0 | `e3b0c44298fc1c14` |

---

*Documentação gerada pelo plugin `scripts/export_bundle.py` — Veltrus Ads Agent*