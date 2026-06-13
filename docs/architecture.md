# Arquitetura

## Visão geral

O Veltrus Ads Agent é um sistema de agentes LLM que opera sobre dados de campanhas armazenados no Supabase e APIs externas (Meta, Google, Brevo). A API FastAPI expõe triggers e o fluxo de aprovação humana; o agente roda como processo Python com LangGraph.

## Stack de produção

```mermaid
flowchart TB
    subgraph clients [Clientes / Operadores]
        WH[WhatsApp]
        OPS[Operador / Cron]
    end

    subgraph infra [Infraestrutura]
        TRAEFIK[Traefik — reverse proxy + TLS]
        API[FastAPI — api]
        WORKER[Celery Worker]
        BEAT[Celery Beat]
        REDIS[(Redis)]
    end

    subgraph external [Serviços externos]
        SUPA[(Supabase Postgres)]
        META[Meta Marketing API]
        GOOGLE[Google Ads API]
        ANTHROPIC[Anthropic Claude]
        N8N[n8n]
        BREVO[Brevo API]
    end

    OPS -->|POST /run| TRAEFIK
    TRAEFIK --> API
    API --> REDIS
    BEAT --> REDIS
    WORKER --> REDIS
    WORKER -->|run_all_accounts| AGENT[LangGraph Agent]

    API --> SUPA
    AGENT --> SUPA
    AGENT --> META
    AGENT --> GOOGLE
    AGENT --> ANTHROPIC
    AGENT -->|notify_human| N8N
    N8N -->|WhatsApp Cloud API| WH
    WH -->|botão aprovar/rejeitar| N8N
    N8N -->|PATCH /decisions| API
    API -->|approve| META
    API -->|approve| GOOGLE

    API -->|POST /run-email| EMAIL[Email LangGraph]
    EMAIL --> BREVO
    EMAIL --> SUPA
```

> **Nota:** Celery, Redis, Traefik e Docker Swarm estão documentados em [deploy.md](./deploy.md). No branch `main`, o deploy atual usa Railway (`railway.json`) ou `uvicorn` direto. A stack Swarm + Traefik é **[PLANEJADO]** — existe referência parcial na branch `cursor/docker-deploy-vps-96fb` com Docker Compose + Caddy.

## Fluxo do agente de ads (implementado)

Hoje o grafo é **monolítico** em `agent/graph.py`. A arquitetura multi-agente com Supervisor está **[PLANEJADO]** (arquivos em `agent/graphs/` são stubs vazios).

```mermaid
flowchart TD
    START([START]) --> ANALISTA[analista]
    ANALISTA -->|anomalias detectadas| ESTRATEGISTA[estrategista]
    ANALISTA -->|sem anomalias| MEMORIZADOR[memorizador]
    ESTRATEGISTA --> REVISOR[revisor]
    REVISOR --> EXECUTOR[executor]
    EXECUTOR --> MEMORIZADOR
    MEMORIZADOR --> END([END])

    ANALISTA -.->|Meta| META_API[Meta API live]
    ANALISTA -.->|Google| SUPA_METRICS[Supabase daily_metrics]
    ESTRATEGISTA -.-> MEM_SEARCH[search_agent_memory]
    EXECUTOR -.->|LOW + autonomous| ADS_API[Meta/Google mutate]
    EXECUTOR -.->|MEDIUM/HIGH ou !autonomous| SAVE[save_decision]
    EXECUTOR -.-> NOTIFY[notify_human → n8n]
    MEMORIZADOR -.-> SAVE_MEM[save_memory]
```

## Arquitetura alvo — Supervisor + sub-agentes [PLANEJADO]

```mermaid
flowchart TB
  subgraph supervisor [SupervisorGraph — PLANEJADO]
    SUP[Supervisor]
  end

  subgraph agents [Sub-agentes — PLANEJADO]
    META_G[Meta Agent Graph]
    GOOGLE_G[Google Agent Graph]
  end

  subgraph nodes [Nós por plataforma — PLANEJADO]
    AN[analyzer]
    OP[optimizer]
    EX[executor]
    RP[reporter]
  end

  TRIGGER[POST /run ou Celery Beat] --> SUP
  SUP -->|platform=meta| META_G
  SUP -->|platform=google| GOOGLE_G
  META_G --> AN --> OP --> EX --> RP
  GOOGLE_G --> AN --> OP --> EX --> RP
  EX --> DECISIONS[(agent_decisions)]
  EX -->|aprovação| N8N[n8n webhook]
```

Arquivos stub (vazios): `agent/graphs/campaign_manager.py`, `agent/graphs/meta_agent.py`, `agent/graphs/google_agent.py`, `agent/nodes/analyzer.py`, `optimizer.py`, `executor.py`, `reporter.py`.

## Fluxo de aprovação humana (n8n → WhatsApp)

O código atual usa **WhatsApp Business Cloud API** via n8n. **Evolution API** não está integrada no repositório — listada como opção futura abaixo.

```mermaid
sequenceDiagram
    participant LG as LangGraph executor
    participant N8N as n8n
    participant WA as WhatsApp Cloud API
    participant H as Humano
    participant API as FastAPI
    participant ADS as Meta/Google API
    participant DB as Supabase

    LG->>DB: save_decision(executed=false)
    LG->>N8N: POST N8N_WEBHOOK_URL
    Note over LG,N8N: decision_id, campaign_name, action_type, risk_level, reasoning, phone_number
    N8N->>WA: Mensagem interativa com botões
    WA->>H: Aprovar / Rejeitar
    H->>WA: Toque no botão
    WA->>N8N: Webhook de resposta
  alt Aprovar
        N8N->>API: PATCH /decisions/{id}/approve
        API->>ADS: Executa ação
        API->>DB: executed=true, approved_by
    else Rejeitar
        N8N->>API: PATCH /decisions/{id}/reject
        API->>DB: approved_by=rejected:...
    end
    N8N->>WA: Confirmação ao usuário
```

### Evolution API [PLANEJADO]

Substituir ou complementar o WhatsApp Cloud API no workflow n8n com [Evolution API](https://github.com/EvolutionAPI/evolution-api) para self-hosting. O contrato do agente permanece o mesmo: `notify_human` envia POST ao webhook n8n; o n8n roteia para Evolution ou Cloud API.

## Agente de email (implementado)

Grafo separado em `agent/email_graph.py`, sem relação com o fluxo de ads:

```mermaid
flowchart LR
    START --> PES[pesquisador]
    PES --> ADL[analista_de_lista]
    ADL --> CP[copywriter]
    CP --> OPT[otimizador]
    OPT --> EXE[executor]
    EXE --> RES[analista_de_resultados]
    RES --> END
```

Disparo: `POST /run-email` com `client_id` e `list_id` (Brevo).

## Kill switch (independente do LangGraph)

```mermaid
flowchart LR
    CRON[cron hourly] --> KS[scripts/kill_switch.py]
    KS --> DB[(daily_metrics + campaigns)]
    KS -->|spend_overage / cpa_spike| PAUSE[Meta/Google pause]
    KS -->|roas_critical| ALERT[alerted only]
    KS --> LOG[(kill_switch_log)]
```

## Camadas de dados

| Camada | Responsabilidade |
|--------|------------------|
| `clients` | Identidade do cliente, `business_dna` (objetivos, restrições) |
| `ad_accounts` | Tokens OAuth por plataforma |
| `campaigns` + `daily_metrics` | Estado e métricas normalizadas |
| `agent_decisions` | Decisões pendentes e histórico de execução |
| `agent_memory` | Memória textual (embeddings [PLANEJADO]) |
| `kill_switch_log` | Auditoria do script de segurança |

Detalhes: [supabase.md](./supabase.md).

## Componentes por status

| Componente | Status | Localização |
|------------|--------|-------------|
| Grafo ads monolítico | Implementado | `agent/graph.py` |
| Grafo email | Implementado | `agent/email_graph.py` |
| Supervisor / Meta / Google graphs | [PLANEJADO] | `agent/graphs/*.py` (vazios) |
| API REST (6 endpoints) | Implementado | `api/` |
| Celery + Redis | [PLANEJADO] no main; parcial em branch docker | `celery_app.py` na branch docker |
| Dashboard Next.js | Scaffold | `dashboard/` |
| WebSocket | [PLANEJADO] | mencionado no README, sem código |
| Evolution API | [PLANEJADO] | não referenciada no código |

## Links

- [agent.md](./agent.md) — detalhes dos nós LangGraph
- [api.md](./api.md) — endpoints
- [integrations.md](./integrations.md) — APIs externas
- [guardrails.md](./guardrails.md) — segurança financeira
- [deploy.md](./deploy.md) — Docker Swarm + Traefik
