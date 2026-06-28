# Veltrus Ads Agent — Documentação Técnica

Agente autônomo de gestão de campanhas de anúncios (Meta Ads e Google Ads) com aprovação humana via WhatsApp, memória persistente e agente de email marketing.

## O que é o Veltrus

A **Veltrus** é uma agência de marketing digital. O **Veltrus Ads Agent** é o sistema que monitora campanhas de anúncios, detecta anomalias de performance (CPA, ROAS, CTR), propõe otimizações via LLM e executa ações nas APIs da Meta e do Google — sempre com camadas de segurança financeira e aprovação humana para decisões de risco médio ou alto.

## Como funciona (em uma página)

1. **Trigger** — Um ciclo é disparado via `POST /run` (API), Celery beat [PLANEJADO] ou `python -m agent.run`.
2. **Coleta** — Para cada conta ativa em `ad_accounts`, o grafo LangGraph busca métricas dos últimos 7 dias (Meta API em tempo real; Google via Supabase).
3. **Análise** — O nó `analista` identifica anomalias (`cpa_spike`, `roas_negative`, `ctr_drop`) usando o schema normalizado `UnifiedMetrics`.
4. **Decisão** — O `estrategista` consulta memória histórica e propõe uma ação (`budget_increase`, `pause_campaign`, etc.).
5. **Revisão de risco** — O `revisor` classifica a decisão como `LOW`, `MEDIUM` ou `HIGH`.
6. **Execução** — O `executor` executa automaticamente (somente `LOW` + `AGENT_AUTONOMOUS_MODE=true`) ou grava em `agent_decisions` e notifica um humano via n8n → WhatsApp.
7. **Aprovação humana** — O operador aprova ou rejeita via `PATCH /decisions/{id}/approve|reject` (direto ou via workflow n8n).
8. **Memória** — O `memorizador` persiste aprendizados em `agent_memory` para ciclos futuros.
9. **Kill switch** — Script independente (`scripts/kill_switch.py`) roda via cron e pausa campanhas que excedem limites financeiros.

Além do agente de ads, existe um **agente de email** (`agent/email_graph.py`) disparado por `POST /run-email`, que cria campanhas no Brevo com pesquisa de mercado, copy e agendamento inteligente.

## Stack

| Camada | Tecnologia | Função |
|--------|------------|--------|
| Agente | Python 3.12 + LangGraph | Orquestração de nós LLM + ferramentas |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) | Análise, decisão e copy |
| API | FastAPI | REST para trigger, decisões e email |
| Banco | Supabase (Postgres + pgvector) | Dados, decisões e memória |
| Fila | Celery + Redis | [PLANEJADO] agendamento de ciclos |
| Frontend | Next.js 14 | [PLANEJADO] dashboard scaffold |
| Deploy | Railway / Docker | Ver [deploy.md](./deploy.md) |

## Estrutura do repositório

```
veltrus-ads-agent/
├── agent/           # Grafos LangGraph, ferramentas e config
│   ├── graph.py     # Grafo de ads (implementado)
│   ├── email_graph.py
│   ├── graphs/      # [PLANEJADO] supervisor, meta, google
│   ├── nodes/       # [PLANEJADO] stubs vazios
│   └── tools/       # Meta, Google, Supabase, Brevo
├── api/             # FastAPI
│   └── routers/     # decisions, run, run-email
├── supabase/        # Migrations SQL
├── scripts/         # kill_switch, seed_test_data
└── docs/            # Esta documentação
```

## Documentação

| Arquivo | Conteúdo |
|---------|----------|
| [architecture.md](./architecture.md) | Diagramas de arquitetura e fluxo completo |
| [api.md](./api.md) | Referência de endpoints REST |
| [agent.md](./agent.md) | LangGraph: estados, nós e fluxo de decisão |
| [supabase.md](./supabase.md) | Schema do banco, RLS e índices |
| [deploy.md](./deploy.md) | Deploy em produção (Docker Swarm + Traefik) |
| [integrations.md](./integrations.md) | Meta, Google, n8n, Brevo |
| [guardrails.md](./guardrails.md) | Regras de segurança e kill switch |

## Setup rápido

```bash
cp .env.example .env
# Preencha ANTHROPIC_API_KEY, SUPABASE_*, API_SECRET_KEY, etc.

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# API
PYTHONPATH=. uvicorn api.main:app --reload --port 8000

# Agente (direto)
PYTHONPATH=. python -m agent.run
```

Documentação interativa da API: `http://localhost:8000/docs`

## Variáveis críticas

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | Sim | LLM do agente |
| `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | Sim | Banco e memória |
| `API_SECRET_KEY` | Sim | Header `X-API-Key` nos endpoints protegidos |
| `AGENT_AUTONOMOUS_MODE` | Não | `false` (padrão) = aprovação humana para ações LOW |
| `N8N_WEBHOOK_URL` | Não | Webhook n8n para notificações WhatsApp |

Lista completa: `.env.example` e [deploy.md](./deploy.md).
