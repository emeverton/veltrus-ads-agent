# Veltrus Ads Agent — Contexto para Claude Code

## O que é este projeto

Agente autônomo de gestão de campanhas de anúncios (Meta Ads e Google Ads).  
O agente monitora métricas, analisa performance e executa otimizações automaticamente usando LLM + LangGraph.

## Stack principal

- **Agente**: Python 3.12 + LangGraph (multi-agente com supervisor pattern)
- **LLM**: Anthropic Claude via `langchain-anthropic` (modelo: `claude-sonnet-4-6`)
- **API**: FastAPI (REST + WebSocket)
- **Banco**: Supabase (Postgres) — dados de campanhas + memória persistente do agente
- **Frontend**: Next.js 14 App Router + Tailwind CSS + shadcn/ui
- **Agendamento**: APScheduler (`python -m agent.main`)

## Arquitetura multi-agente (LangGraph)

```
SupervisorGraph
├── MetaAgent Graph      → campanha Facebook/Instagram
│   ├── node: analyzer
│   ├── node: optimizer
│   └── node: executor
└── GoogleAgent Graph    → campanha Google Ads
    ├── node: analyzer
    ├── node: optimizer
    └── node: executor

Nós compartilhados:
- reporter   → gera summaries e alertas
- memory     → lê/grava no Supabase
```

## Estrutura de pastas crítica

```
agent/
  graphs/        # Definições dos grafos LangGraph
  nodes/         # Implementação de cada nó
  tools/         # Ferramentas (Meta API, Google API, Supabase)
  memory/        # Memória persistente (short-term e long-term)
  prompts/       # System prompts e templates

api/
  routers/       # campaigns, analytics, agents, webhooks
  models/        # Schemas Pydantic

dashboard/
  app/           # Next.js App Router
  components/    # Componentes React (shadcn/ui base)
  lib/           # api.ts (cliente axios), utils.ts

supabase/
  migrations/    # SQL migrations versionadas
```

## Convenções de código

### Python (agent/ e api/)
- Python 3.12, type hints obrigatórios
- Pydantic v2 para schemas
- `structlog` para logging (não `print` ou `logging` direto)
- Async por padrão (`async def`) nos nós e routers
- Prefixo `_` em variáveis privadas de módulo

### TypeScript (dashboard/)
- Next.js 14 App Router (não Pages Router)
- Server Components por padrão; `"use client"` só quando necessário
- Componentes UI via shadcn/ui — não criar componentes UI do zero
- `@tanstack/react-query` para fetching de dados no cliente
- Zod para validação de formulários

## Variáveis de ambiente importantes

Veja `.env.example` para a lista completa.  
Chaves críticas:
- `ANTHROPIC_API_KEY` — LLM do agente
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` — banco + memória
- `META_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID` — Meta Ads API
- `GOOGLE_ADS_*` — Google Ads API
- `AGENT_AUTONOMOUS_MODE` — **false** em dev, true só em prod validado

## Segurança — regras importantes

- **Nunca** commitar `.env` (está no `.gitignore`)
- Todas as ações destrutivas do agente (pause, delete, budget cut) precisam passar por `AGENT_AUTONOMOUS_MODE=true` + confirmação de limite (`AGENT_MAX_DAILY_SPEND_USD`)
- O agente deve sempre logar a intenção antes de executar uma ação via API externa
- Tokens de acesso Meta/Google são renovados automaticamente; não hardcodar no código

## Estado atual do projeto

Estrutura criada, sem implementação. Próximos passos esperados:
1. Schema do banco Supabase (`supabase/migrations/`)
2. Cliente Supabase e ferramentas base (`agent/tools/`)
3. Definição dos grafos LangGraph (`agent/graphs/`)
4. Endpoints FastAPI (`api/routers/`)
5. Componentes do dashboard (`dashboard/`)
