# Veltrus Ads Agent

Agente autônomo de gestão de campanhas de anúncios para Meta Ads e Google Ads.

## Visão Geral

O Veltrus Ads Agent é um sistema multi-agente que monitora, analisa e otimiza campanhas de ads de forma autônoma. O agente toma decisões baseadas em dados históricos, metas de performance e regras de negócio configuráveis.

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                        Dashboard (Next.js)                  │
│              Visualização · Configuração · Alertas          │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP / WebSocket
┌───────────────────────────▼─────────────────────────────────┐
│                        API (FastAPI)                        │
│           Autenticação · Roteamento · Webhooks              │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Agente (LangGraph)                        │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │ Supervisor  │  │  Meta Agent │  │  Google Agent    │   │
│  │   Graph     │─▶│   Graph     │  │     Graph        │   │
│  └─────────────┘  └─────────────┘  └──────────────────┘   │
│                                                             │
│  Nodes: Analyzer · Optimizer · Executor · Reporter         │
└───────┬───────────────────────┬─────────────────────────────┘
        │                       │
┌───────▼──────┐    ┌───────────▼──────────────────────────┐
│  Supabase    │    │         APIs Externas                 │
│  · Database  │    │  · Meta Marketing API                 │
│  · Auth      │    │  · Google Ads API                    │
│  · Memória   │    │  · Anthropic API (Claude)            │
└──────────────┘    └──────────────────────────────────────┘
```

## Stack

| Camada       | Tecnologia                    | Função                                    |
|--------------|-------------------------------|-------------------------------------------|
| Agente       | Python + LangGraph            | Orquestração multi-agente e lógica de IA |
| LLM          | Anthropic Claude (claude-sonnet-4-6) | Raciocínio e tomada de decisão     |
| API          | FastAPI                       | Interface REST + WebSocket para dashboard |
| Banco        | Supabase (Postgres)           | Dados, autenticação e memória persistente |
| Frontend     | Next.js 14 + Tailwind + shadcn | Dashboard de visualização e controle     |

## Estrutura de Pastas

```
veltrus-ads-agent/
├── agent/                    # Core do agente Python
│   ├── graphs/               # Grafos LangGraph (supervisor, meta, google)
│   ├── nodes/                # Nós dos grafos (analyzer, optimizer, executor, reporter)
│   ├── tools/                # Ferramentas (Meta API, Google API, Supabase)
│   ├── memory/               # Memória persistente do agente
│   └── prompts/              # Templates de prompts do sistema
├── api/                      # FastAPI backend
│   ├── routers/              # Endpoints (campaigns, analytics, agents, webhooks)
│   └── models/               # Schemas Pydantic
├── dashboard/                # Frontend Next.js
│   ├── app/                  # App Router (campaigns, analytics, settings)
│   ├── components/           # Componentes React + shadcn/ui
│   ├── lib/                  # Utilitários e cliente API
│   └── types/                # TypeScript types
├── supabase/                 # Migrations e seed do banco
├── tests/                    # Testes unitários e de integração
├── docs/                     # Documentação técnica
└── scripts/                  # Setup e deploy
```

## Fluxo do Agente

1. **Coleta** — O agente busca métricas das campanhas ativas (Meta e Google) em intervalos configuráveis
2. **Análise** — O nó `Analyzer` avalia performance vs. metas (ROAS, CPA, CTR, etc.)
3. **Decisão** — O `Supervisor Graph` decide quais ações tomar com base na análise
4. **Execução** — O nó `Executor` aplica otimizações via API (ajuste de lance, pause, budget)
5. **Memória** — Todas as ações e resultados são gravados no Supabase para aprendizado futuro
6. **Relatório** — O nó `Reporter` gera summaries e dispara alertas quando necessário

## Setup Rápido

```bash
# 1. Clone e configure variáveis de ambiente
cp .env.example .env
# Preencha todas as variáveis no .env

# 2. Backend Python
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Frontend
cd dashboard
npm install
npm run dev

# 4. API
uvicorn api.main:app --reload --port 8000

# 5. Agente
python -m agent.main
```

## Variáveis de Ambiente

Veja `.env.example` para a lista completa de variáveis necessárias.

## API de Decisões — Aprovação Humana

### Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/decisions` | Lista decisões pendentes com dados da campanha |
| `PATCH` | `/decisions/{id}/approve` | Aprova e executa via Meta/Google API |
| `PATCH` | `/decisions/{id}/reject` | Rejeita com motivo (sem chamar APIs externas) |

Todos os endpoints requerem o header `X-API-Key: {API_SECRET_KEY}`.

### Iniciar a API

```bash
PYTHONPATH=. uvicorn api.main:app --reload --port 8000
```

Documentação interativa: `http://localhost:8000/docs`

### Exemplos de chamada

```bash
# Listar pendentes
curl http://localhost:8000/decisions \
  -H "X-API-Key: $API_SECRET_KEY"

# Aprovar
curl -X PATCH http://localhost:8000/decisions/{id}/approve \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "joao@empresa.com"}'

# Rejeitar
curl -X PATCH http://localhost:8000/decisions/{id}/reject \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rejected_by": "joao@empresa.com", "reason": "Budget já foi ajustado manualmente"}'
```

### Estados de uma decisão

```
agent_decisions.executed | approved_at | Significado
false                    | null        | ⏳ Pendente (aparece no GET /decisions)
true                     | preenchido  | ✅ Aprovada e executada
false                    | preenchido  | ❌ Rejeitada (approved_by = "rejected:{email}")
```

---

## Aprovação via WhatsApp — Integração n8n

O agente dispara `notify_human()` toda vez que uma decisão precisa de aprovação humana. Quando `N8N_WEBHOOK_URL` está configurado, o agente faz `POST` ao n8n com o seguinte payload:

```json
{
  "decision_id":   "uuid-da-decisao",
  "campaign_name": "Campanha Black Friday",
  "action_type":   "budget_increase",
  "risk_level":    "MEDIUM",
  "reasoning":     "ROAS 3.8x acima da meta, CPA abaixo do limite. Recomendo +20% no budget.",
  "phone_number":  "5511999998888"
}
```

### Fluxo completo

```
Agente LangGraph
  └─ notify_human()
       └─ POST → N8N_WEBHOOK_URL
                    │
              ┌─────▼─────────────────────────────┐
              │  n8n Workflow                      │
              │                                    │
              │  1. Webhook (trigger)              │
              │  2. Format WhatsApp message        │
              │  3. HTTP → WhatsApp Business API   │
              │     (mensagem interativa c/ botões)│
              └────────────────────────────────────┘
                    │  Usuário toca botão
              ┌─────▼─────────────────────────────┐
              │  4. Webhook (resposta WhatsApp)    │
              │  5. Switch: Aprovar / Rejeitar     │
              │  6a. PATCH /decisions/{id}/approve │
              │  6b. PATCH /decisions/{id}/reject  │
              │  7. WhatsApp: confirma ação        │
              └────────────────────────────────────┘
                    │
              Supabase atualizado + API executada
```

### Configuração do Workflow n8n

#### Node 1 — Webhook (recebe do agente)

- **Type:** Webhook
- **HTTP Method:** POST
- **Path:** `/webhook/agent-decision`
- **Authentication:** Header Auth → `X-Webhook-Secret: {segredo_compartilhado}`

#### Node 2 — Send WhatsApp Message (HTTP Request)

Chama a [WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons-messages) com mensagem interativa:

- **Method:** POST
- **URL:** `https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages`
- **Headers:** `Authorization: Bearer {WHATSAPP_TOKEN}`
- **Body (JSON):**

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "{{$json.phone_number}}",
  "type": "interactive",
  "interactive": {
    "type": "button",
    "body": {
      "text": "🤖 *Veltrus Ads Agent*\n\n*Campanha:* {{$json.campaign_name}}\n*Ação:* {{$json.action_type}}\n*Risco:* {{$json.risk_level}}\n\n_{{$json.reasoning}}_\n\nID: `{{$json.decision_id}}`"
    },
    "action": {
      "buttons": [
        {
          "type": "reply",
          "reply": { "id": "approve_{{$json.decision_id}}", "title": "✅ Aprovar" }
        },
        {
          "type": "reply",
          "reply": { "id": "reject_{{$json.decision_id}}", "title": "❌ Rejeitar" }
        }
      ]
    }
  }
}
```

#### Node 3 — Webhook (recebe resposta do WhatsApp)

Configure o webhook do WhatsApp Business para enviar callbacks ao n8n:

- **URL de verificação:** `https://n8n.example.com/webhook/whatsapp-reply`
- O n8n recebe o objeto `messages[0].interactive.button_reply`

#### Node 4 — Switch (Aprovar vs Rejeitar)

- **Condition:** `{{$json.body.entry[0].changes[0].value.messages[0].interactive.button_reply.id}}` starts with `approve_`

**Branch Aprovar → Node 5a — HTTP Request:**
```
PATCH https://api.seuservidor.com/decisions/{decision_id}/approve
X-API-Key: {API_SECRET_KEY}
Body: {"approved_by": "whatsapp:5511999998888"}
```

**Branch Rejeitar → Node 5b — Set + HTTP Request:**
```
PATCH https://api.seuservidor.com/decisions/{decision_id}/reject
X-API-Key: {API_SECRET_KEY}
Body: {"rejected_by": "whatsapp:5511999998888", "reason": "Rejeitado via WhatsApp"}
```

#### Node 6 — Confirmação WhatsApp (HTTP Request)

Envia mensagem de texto simples confirmando a ação ao usuário.

### Variáveis de ambiente necessárias

```bash
N8N_WEBHOOK_URL=https://n8n.example.com/webhook/agent-decision
NOTIFY_PHONE_NUMBER=5511999998888    # número que receberá as mensagens
```

### Alternativa: Make.com

O mesmo fluxo pode ser montado no Make.com com os módulos:
1. **Webhooks → Custom Webhook** (trigger)
2. **HTTP → Make a request** (enviar WhatsApp)
3. **Webhooks → Custom Webhook** (resposta WhatsApp)
4. **Router** → branch Aprovar / Rejeitar
5. **HTTP → Make a request** (PATCH approve ou reject)

---

## Kill Switch — Proteção Financeira

O `scripts/kill_switch.py` é um script de segurança **independente do agente LangGraph** que roda a cada hora via cron e aplica 3 regras:

| Regra | Condição | Ação |
|-------|----------|------|
| `spend_overage` | gasto hoje > `daily_budget × 1.1` | Pausa campanha + log |
| `cpa_spike` | CPA hoje > `cpa_max × 2.0` | Pausa campanha + log |
| `roas_critical` | ROAS hoje < `0.5` | Alerta + log (sem pausa) |

O `cpa_max` é extraído do campo `business_dna.objetivo_principal` do cliente (ex.: `"maximizar ROAS mantendo CPA < $25"`). Todas as ações são registradas na tabela `kill_switch_log` no Supabase.

### Execução manual

```bash
# Modo real
PYTHONPATH=. python scripts/kill_switch.py

# Simulação (não chama APIs externas, registra como dry_run)
PYTHONPATH=. python scripts/kill_switch.py --dry-run
```

### Cron job (recomendado: a cada hora)

Adicione ao crontab com `crontab -e`:

```cron
# Kill switch — roda todo início de hora
# Ajuste o caminho do Python e do projeto conforme seu ambiente

# 0 * * * * cd /caminho/para/veltrus-ads-agent && PYTHONPATH=. /usr/bin/python3 scripts/kill_switch.py >> /var/log/kill_switch.log 2>&1
```

Para usar o Python 3.12 do runtime do projeto:

```cron
# 0 * * * * cd /Users/emh/veltrus-ads-agent && PYTHONPATH=. ~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3.12 scripts/kill_switch.py >> /tmp/kill_switch.log 2>&1
```

### Logs

Estruturados via `structlog`. Entradas críticas (regra disparada) aparecem como `kill_switch.spend_overage`, `kill_switch.cpa_spike` ou `kill_switch.roas_critical` com nível `CRITICAL`. Consulte o histórico auditável na tabela `kill_switch_log`.

## Documentação

- [Arquitetura detalhada](docs/architecture.md)
- [Referência da API](docs/api.md)
- [Documentação completa do projeto](docs/PROJETO_COMPLETO.md) — gerada automaticamente

---

## Exportar Pacote Completo

O plugin `scripts/export_bundle.py` gera um ZIP com todo o código-fonte, migrations, documentação detalhada e manifesto de arquivos.

```bash
# Gerar pacote ZIP completo (salva em dist/)
python scripts/export_bundle.py

# Especificar caminho de saída
python scripts/export_bundle.py --output ./veltrus-completo.zip

# Apenas gerar documentação (sem ZIP)
python scripts/export_bundle.py --docs-only
```

**Conteúdo do pacote exportado:**

| Item | Descrição |
|------|-----------|
| Código-fonte | agent/, api/, dashboard/, scripts/ |
| Migrations | supabase/migrations/ (4 arquivos SQL) |
| Docker | Dockerfile, docker-compose.yml, Caddyfile |
| `docs/PROJETO_COMPLETO.md` | Documentação detalhada de tudo implementado |
| `MANIFEST.json` | Inventário com checksums SHA256 |

Arquivos excluídos automaticamente: `.env`, `.git`, `node_modules`, `venv`, `__pycache__`.
