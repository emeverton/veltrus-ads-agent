# API Reference — Veltrus Ads Agent

**Base URL:** `https://api.seudominio.com` (produção) | `http://localhost:8000` (dev)

**Autenticação:** todos os endpoints (exceto `/health`) exigem o header:
```
X-API-Key: {API_SECRET_KEY}
```

**Documentação interativa:** `GET /docs` (Swagger UI) | `GET /redoc` (ReDoc)

---

## Endpoints Disponíveis

| Método | Path | Tags | Descrição |
|--------|------|------|-----------|
| `GET` | `/health` | system | Health check |
| `POST` | `/run` | agent | Dispara ciclo completo do agente |
| `GET` | `/decisions` | decisions | Lista decisões pendentes de aprovação |
| `PATCH` | `/decisions/{id}/approve` | decisions | Aprova e executa ação |
| `PATCH` | `/decisions/{id}/reject` | decisions | Rejeita decisão |
| `POST` | `/run-email` | email | Dispara Agente de Email Marketing |

---

## GET /health

Verifica se a API está online. Não requer autenticação.

**Request**
```bash
curl http://localhost:8000/health
```

**Response 200**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## POST /run

Dispara `run_all_accounts()` em background e retorna imediatamente. O agente busca todas as contas de ads ativas no Supabase e executa o grafo LangGraph para cada uma sequencialmente.

**Headers**
```
X-API-Key: {API_SECRET_KEY}
```

**Request**
```bash
curl -X POST http://localhost:8000/run \
  -H "X-API-Key: $API_SECRET_KEY"
```

**Response 200**
```json
{
  "status": "started",
  "timestamp": "2026-06-13T10:30:00.123456+00:00"
}
```

**Observações**
- O endpoint retorna antes do ciclo terminar. O processamento ocorre em `BackgroundTasks`.
- Cada conta é processada sequencialmente para respeitar os rate limits das APIs.
- O progresso pode ser acompanhado pelos logs estruturados (`structlog`) ou pelas decisões criadas em `agent_decisions`.

---

## GET /decisions

Lista todas as decisões **pendentes** de aprovação humana, ou seja, onde `executed=false` e `approved_at IS NULL`.

**Headers**
```
X-API-Key: {API_SECRET_KEY}
```

**Request**
```bash
curl http://localhost:8000/decisions \
  -H "X-API-Key: $API_SECRET_KEY"
```

**Response 200** — Array de `DecisionOut`
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "action_type": "budget_increase",
    "reasoning": "ROAS 3.8x acima da meta durante os últimos 3 dias. CPA de $12.40 abaixo do limite de $20. Margem de escala disponível. Recomendo aumento de 15% no budget para capturar mais volume.",
    "payload": {
      "new_budget_usd": 172.5,
      "budget_change_pct": 15.0
    },
    "executed": false,
    "approved_by": null,
    "approved_at": null,
    "created_at": "2026-06-13T10:15:30.000000+00:00",
    "campaign": {
      "id": "campaign-uuid",
      "name": "Campanha Black Friday",
      "campaign_id": "120200123456",
      "platform": "meta",
      "daily_budget": "150.00"
    },
    "ad_account": {
      "id": "account-uuid",
      "account_id": "act_123456789",
      "platform": "meta"
    }
  }
]
```

**Estados de uma decisão**

| `executed` | `approved_at` | Estado |
|-----------|--------------|--------|
| `false` | `null` | ⏳ Pendente (aparece neste endpoint) |
| `true` | preenchido | ✅ Aprovada e executada |
| `false` | preenchido | ❌ Rejeitada (`approved_by = "rejected:{email}"`) |

---

## PATCH /decisions/{id}/approve

Aprova uma decisão pendente e executa a ação correspondente via Meta Ads API ou Google Ads API.

**Headers**
```
X-API-Key: {API_SECRET_KEY}
Content-Type: application/json
```

**Path Parameter**
| Nome | Tipo | Descrição |
|------|------|-----------|
| `id` | UUID | ID da decisão em `agent_decisions` |

**Request Body**
```json
{
  "approved_by": "joao@empresa.com"
}
```

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| `approved_by` | string | `"human"` | Identificador de quem aprovou |

**Request**
```bash
curl -X PATCH http://localhost:8000/decisions/550e8400-e29b-41d4-a716-446655440000/approve \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "joao@empresa.com"}'
```

**Response 200**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "approved",
  "action_type": "budget_increase",
  "approved_by": "joao@empresa.com",
  "api_result": {
    "campaign_id": "120200123456",
    "daily_budget_usd": 172.5,
    "result": {}
  }
}
```

**Erros**
| Status | Condição |
|--------|---------|
| `403` | API key inválida |
| `404` | Decisão não encontrada |
| `409` | Decisão já executada ou já rejeitada |
| `422` | Payload inválido (ex: `daily_budget_usd` ausente para ação de budget) |
| `502` | Falha na chamada à API da plataforma de ads |

**Ações suportadas por plataforma**

*Meta Ads:*
- `pause_campaign` — pausa via `Campaign.remote_update(status=PAUSED)`
- `activate_campaign` — ativa via `Campaign.remote_update(status=ACTIVE)`
- `budget_increase` / `budget_decrease` — requer `daily_budget_usd` ou `new_budget_usd` no payload

*Google Ads:*
- `pause_campaign` — pausa via `CampaignService.mutate_campaigns(status=PAUSED)`
- `activate_campaign` — ativa via `CampaignService.mutate_campaigns(status=ENABLED)`
- `budget_increase` / `budget_decrease` — requer `campaign_budget_id` e `amount_micros` no payload

---

## PATCH /decisions/{id}/reject

Rejeita uma decisão pendente. **Não chama nenhuma API externa.** Registra a rejeição no Supabase.

**Headers**
```
X-API-Key: {API_SECRET_KEY}
Content-Type: application/json
```

**Path Parameter**
| Nome | Tipo | Descrição |
|------|------|-----------|
| `id` | UUID | ID da decisão em `agent_decisions` |

**Request Body**
```json
{
  "rejected_by": "joao@empresa.com",
  "reason": "Budget já foi ajustado manualmente ontem"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `rejected_by` | string | não (padrão: `"human"`) | Identificador de quem rejeitou |
| `reason` | string | **sim** | Motivo da rejeição (salvo no payload da decisão) |

**Request**
```bash
curl -X PATCH http://localhost:8000/decisions/550e8400-e29b-41d4-a716-446655440000/reject \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rejected_by": "joao@empresa.com", "reason": "Budget já ajustado manualmente"}'
```

**Response 200**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "rejected",
  "action_type": "budget_increase",
  "rejected_by": "joao@empresa.com",
  "reason": "Budget já ajustado manualmente"
}
```

**Efeito no banco:**
```
agent_decisions.executed    = false
agent_decisions.approved_by = "rejected:joao@empresa.com"
agent_decisions.approved_at = <timestamp da rejeição>
agent_decisions.payload     = {...original, "rejection_reason": "...", "rejected_by": "..."}
```

---

## POST /run-email

Dispara o Agente de Email Marketing em background para um cliente específico. O agente executa 6 nós em sequência: PESQUISADOR → ANALISTA_DE_LISTA → COPYWRITER → OTIMIZADOR → EXECUTOR → ANALISTA_DE_RESULTADOS.

**Headers**
```
X-API-Key: {API_SECRET_KEY}
Content-Type: application/json
```

**Request Body**
```json
{
  "client_id": "client-uuid",
  "list_id": 123,
  "context": "Foco na campanha de Dia dos Namorados. Priorizar produtos acima de R$200."
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `client_id` | UUID | **sim** | UUID do cliente em `public.clients` |
| `list_id` | integer | **sim** | ID da lista de contatos no Brevo |
| `context` | string | não (padrão: `""`) | Contexto adicional para o PESQUISADOR e COPYWRITER |

**Request**
```bash
curl -X POST http://localhost:8000/run-email \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "550e8400-e29b-41d4-a716-446655440000",
    "list_id": 123,
    "context": "Foco em produtos de verão, temporada alta"
  }'
```

**Response 200**
```json
{
  "status": "started",
  "client_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-06-13T10:30:00.123456+00:00"
}
```

**Erros**
| Status | Condição |
|--------|---------|
| `403` | API key inválida |
| `404` | `client_id` não encontrado em `public.clients` |

**Observações**
- O endpoint retorna antes da execução terminar. O grafo roda em uma thread dedicada com seu próprio event loop.
- O EXECUTOR cria a campanha no Brevo e insere/atualiza a linha em `email_campaigns`.
- O ANALISTA_DE_RESULTADOS é chamado imediatamente após o disparo; se a campanha foi agendada, retornará métricas parciais (zeradas) até o envio ocorrer.

---

## Observações de Segurança

- O header `X-API-Key` é validado contra `settings.api_secret_key` (variável `API_SECRET_KEY`).
- Tokens de acesso das plataformas de ads (`ad_accounts.token`) **nunca** são retornados pelos endpoints. O campo é removido em `_format_decision()` antes de serializar.
- Todas as requisições são logadas via `structlog` com nível de log configurável por `DEBUG`.
- CORS configurado via `API_ALLOWED_ORIGINS` (padrão: `http://localhost:3000`).
