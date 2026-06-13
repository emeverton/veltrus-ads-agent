# Veltrus Ads Agent — Visão Geral

**Agente autônomo de gestão de campanhas de anúncios (Meta Ads + Google Ads) com LLM + LangGraph.**

---

## O que é o Veltrus Ads Agent

O Veltrus Ads Agent é um sistema de inteligência artificial que monitora, analisa e otimiza campanhas de anúncios digitais de forma autônoma ou semi-autônoma. Ele executa ciclos de análise a cada `AGENT_CYCLE_INTERVAL_MINUTES` minutos (padrão: 30 min), identifica anomalias de performance, propõe ou executa ações corretivas e mantém uma memória persistente para aprender com cada ciclo.

O sistema foi projetado para operar em dois modos:
- **Modo Autônomo** (`AGENT_AUTONOMOUS_MODE=true`): executa ações de baixo risco diretamente via API das plataformas de ads, sem intervenção humana.
- **Modo Supervisionado** (`AGENT_AUTONOMOUS_MODE=false`): todas as ações são enfileiradas para aprovação humana via WhatsApp (através do n8n + Evolution API) ou via dashboard.

---

## Como funciona em uma página

```
┌──────────────────────────────────────────────────────────────────┐
│  CICLO DO AGENTE (a cada 30 min)                                 │
│                                                                  │
│  1. Busca todas as contas de ads ativas no Supabase              │
│                                                                  │
│  2. Para cada conta, executa o grafo LangGraph:                  │
│                                                                  │
│     ANALISTA → detecta anomalias (CPA spike, ROAS negativo,      │
│                CTR drop) usando Meta API ou Google Ads API       │
│                                                                  │
│     ESTRATEGISTA → consulta memória histórica e decide a         │
│                    ação: pause, budget+/-, activate, monitor     │
│                                                                  │
│     REVISOR → classifica o risco: LOW / MEDIUM / HIGH            │
│                                                                  │
│     EXECUTOR → executa via API (se LOW + autônomo)               │
│                OU enfileira para aprovação humana                │
│                                                                  │
│     MEMORIZADOR → salva insights no Supabase para ciclos futuros │
│                                                                  │
│  3. Kill switch independente (a cada hora via cron):             │
│     verifica spend_overage, cpa_spike e roas_critical            │
│     e pausa campanhas em emergência sem passar pelo LLM          │
└──────────────────────────────────────────────────────────────────┘

Aprovação humana:
  Agente → n8n Webhook → Evolution API → WhatsApp (botões Aprovar/Rejeitar)
  Resposta do usuário → n8n → PATCH /decisions/{id}/approve
```

---

## Stack

| Camada | Tecnologia | Versão mínima |
|--------|-----------|---------------|
| Agente / Orquestração | Python + LangGraph | 3.12 / ≥0.2.0 |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) | anthropic ≥0.40.0 |
| API | FastAPI + Uvicorn | ≥0.115.0 |
| Banco de Dados | Supabase (Postgres + pgvector) | supabase-py ≥2.9.0 |
| Frontend | Next.js 14 App Router + Tailwind + shadcn/ui | Next.js 14 |
| Fila / Agendamento | Celery + Redis | ≥5.4.0 / ≥5.2.0 |
| Meta Ads | facebook-business SDK | ≥21.0.0 (API v21.0) |
| Google Ads | google-ads Python client | ≥25.0.0 |
| Email Marketing | Brevo API v3 (HTTP direto) | — |
| Notificações | n8n + Evolution API → WhatsApp | — |
| Infraestrutura | Docker Swarm + Portainer + Traefik | — |

---

## Estrutura de pastas

```
veltrus-ads-agent/
├── agent/
│   ├── config.py              # Settings (pydantic-settings, lê .env)
│   ├── graph.py               # Grafo principal de ads (5 nós LangGraph)
│   ├── email_graph.py         # Grafo de email marketing (6 nós LangGraph)
│   ├── run.py                 # Ponto de entrada: run_all_accounts()
│   ├── graphs/
│   │   ├── meta_agent.py      # [PLANEJADO] Grafo especializado Meta
│   │   ├── google_agent.py    # [PLANEJADO] Grafo especializado Google
│   │   └── campaign_manager.py # [PLANEJADO] Supervisor multi-conta
│   ├── nodes/                 # [PLANEJADO] Nós modulares reutilizáveis
│   ├── tools/
│   │   ├── meta_ads.py        # Integração Meta Ads API (facebook-business)
│   │   ├── google_ads.py      # Integração Google Ads API (GAQL + mutate)
│   │   ├── email_brevo.py     # Integração Brevo API v3
│   │   ├── normalizer.py      # Unified Marketing Schema (cross-platform)
│   │   └── supabase_client.py # Cliente Supabase (service_role)
│   ├── memory/                # [PLANEJADO] Abstrações de memória
│   └── prompts/               # [PLANEJADO] Templates de system prompts
│
├── api/
│   ├── main.py                # FastAPI app, CORS, exception handlers
│   ├── routers/
│   │   ├── run.py             # POST /run — dispara ciclo em background
│   │   ├── decisions.py       # GET/PATCH /decisions — aprovação humana
│   │   ├── run_email.py       # POST /run-email — dispara agente de email
│   │   ├── campaigns.py       # [PLANEJADO]
│   │   ├── analytics.py       # [PLANEJADO]
│   │   ├── agents.py          # [PLANEJADO]
│   │   └── webhooks.py        # [PLANEJADO]
│   └── models/schemas.py      # Schemas Pydantic
│
├── dashboard/                 # Next.js 14 App Router
│   ├── app/                   # Páginas (campaigns, analytics, settings)
│   ├── lib/api.ts             # Cliente HTTP para a FastAPI
│   └── types/index.ts         # TypeScript types
│
├── supabase/
│   └── migrations/            # SQL versionado (001 → 004)
│
├── scripts/
│   ├── kill_switch.py         # Proteção financeira (cron, independente do LLM)
│   ├── seed_test_data.py      # Dados de teste
│   └── setup.sh               # Setup inicial do ambiente
│
└── docs/                      # Esta documentação
```

---

## Documentação

| Arquivo | Conteúdo |
|---------|---------|
| [architecture.md](./architecture.md) | Diagrama Mermaid do fluxo completo e stack detalhada |
| [api.md](./api.md) | Todos os endpoints com exemplos de request/response |
| [agent.md](./agent.md) | LangGraph: estados, nós, grafos, fluxo de decisão |
| [supabase.md](./supabase.md) | Schema completo das tabelas, campos, tipos e RLS |
| [deploy.md](./deploy.md) | Guia de deploy Docker Swarm via Portainer + Traefik |
| [integrations.md](./integrations.md) | Meta Ads, Google Ads, Evolution API, n8n, Brevo |
| [guardrails.md](./guardrails.md) | Regras de segurança financeira e kill switch |
