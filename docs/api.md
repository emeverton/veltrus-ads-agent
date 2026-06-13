# Referência da API

Base URL: `http://localhost:8000` (dev) ou URL de produção atrás do Traefik.

Documentação interativa: `/docs` (Swagger) e `/redoc`.

## Autenticação

Todos os endpoints exceto `/health` exigem o header:

```
X-API-Key: {API_SECRET_KEY}
```

Validação em `api/routers/decisions.py`:

```python
def _require_api_key(key: str = Security(_api_key_header)) -> str:
    if key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key
```

## Endpoints ativos

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| `GET` | `/health` | Não | Health check |
| `GET` | `/decisions` | Sim | Lista decisões pendentes |
| `PATCH` | `/decisions/{id}/approve` | Sim | Aprova e executa via Meta/Google |
| `PATCH` | `/decisions/{id}/reject` | Sim | Rejeita sem executar |
| `POST` | `/run` | Sim | Dispara ciclo do agente de ads |
| `POST` | `/run-email` | Sim | Dispara agente de email (Brevo) |

Routers **não montados** (stubs vazios): `campaigns`, `analytics`, `agents`, `webhooks` — ver comentário em `api/main.py`.

---

## `GET /health`

Verifica se a API está respondendo. Usado pelo healthcheck do Railway e Docker.

**Request:** sem body, sem auth.

**Response `200`:**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

**Exemplo:**

```bash
curl http://localhost:8000/health
```

---

## `GET /decisions`

Lista decisões **pendentes** de aprovação (`executed=false` e `approved_at` nulo).

**Response `200`:** array de `DecisionOut`

```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "action_type": "budget_increase",
    "reasoning": "ROAS 3.2x acima da meta nos últimos 3 dias. CPA estável em $18.",
    "payload": {
      "params": { "new_budget_usd": 120.0, "budget_change_pct": 20.0 }
    },
    "executed": false,
    "approved_by": null,
    "approved_at": null,
    "created_at": "2026-06-13T14:30:00+00:00",
    "campaign": {
      "id": "camp-uuid-interno",
      "name": "Campanha Black Friday",
      "campaign_id": "23850123456789",
      "platform": "meta",
      "daily_budget": 100.0
    },
    "ad_account": {
      "id": "account-uuid",
      "account_id": "123456789",
      "platform": "meta"
    }
  }
]
```

> O campo `token` da conta é removido na resposta (`_format_decision`).

**Erros:**

| Status | Causa |
|--------|-------|
| `403` | `X-API-Key` inválida |
| `503` | Falha na query Supabase |

**Exemplo:**

```bash
curl http://localhost:8000/decisions \
  -H "X-API-Key: $API_SECRET_KEY"
```

---

## `PATCH /decisions/{decision_id}/approve`

Aprova uma decisão pendente e executa a ação na API da plataforma (Meta ou Google).

**Path param:** `decision_id` — UUID em `agent_decisions.id`

**Request body:**

```json
{
  "approved_by": "joao@empresa.com"
}
```

| Campo | Tipo | Default | Descrição |
|-------|------|---------|-----------|
| `approved_by` | `string` | `"human"` | Identificador do aprovador |

**Response `200`:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "approved",
  "action_type": "budget_increase",
  "approved_by": "whatsapp:5511999998888",
  "api_result": {
    "success": true,
    "campaign_id": "23850123456789",
    "new_daily_budget_usd": 120.0
  }
}
```

O `api_result` reflete o retorno real de `meta_ads.*` ou `google_ads.*` e é também persistido em `agent_decisions.payload.api_result`.

**Erros:**

| Status | Causa |
|--------|-------|
| `404` | Decisão não encontrada |
| `409` | Já executada ou já revisada (rejeitada) |
| `422` | Payload incompleto (ex.: falta `daily_budget_usd` para Meta) |
| `502` | Falha na API externa |
| `403` | API key inválida |

**Payloads exigidos por ação:**

| Plataforma | Ação | Campos obrigatórios no `payload` |
|------------|------|----------------------------------|
| Meta | `budget_increase` / `budget_decrease` | `daily_budget_usd` ou `new_budget_usd` (ou em `params`) |
| Google | `budget_increase` / `budget_decrease` | `campaign_budget_id`, `amount_micros` |
| Ambas | `pause_campaign` / `activate_campaign` | IDs da campanha via join com `campaigns` |

**Exemplo:**

```bash
curl -X PATCH "http://localhost:8000/decisions/a1b2c3d4-.../approve" \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "joao@empresa.com"}'
```

---

## `PATCH /decisions/{decision_id}/reject`

Rejeita uma decisão pendente. **Não chama** APIs externas.

**Request body:**

```json
{
  "rejected_by": "joao@empresa.com",
  "reason": "Budget já foi ajustado manualmente"
}
```

| Campo | Tipo | Default | Descrição |
|-------|------|---------|-----------|
| `rejected_by` | `string` | `"human"` | Identificador |
| `reason` | `string` | — | Motivo (obrigatório) |

**Response `200`:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "rejected",
  "action_type": "budget_increase",
  "rejected_by": "joao@empresa.com",
  "reason": "Budget já foi ajustado manualmente"
}
```

No banco: `approved_by = "rejected:{rejected_by}"`, `approved_at` preenchido, `executed = false`.

**Exemplo:**

```bash
curl -X PATCH "http://localhost:8000/decisions/a1b2c3d4-.../reject" \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rejected_by": "joao@empresa.com", "reason": "Budget já foi ajustado manualmente"}'
```

---

## `POST /run`

Dispara `run_all_accounts()` em background (FastAPI `BackgroundTasks`). Retorna imediatamente.

**Request:** sem body.

**Response `200`:**

```json
{
  "status": "started",
  "timestamp": "2026-06-13T15:00:00.123456+00:00"
}
```

**Comportamento:** para cada `ad_accounts` ativa com `clients.active=true`, executa `compiled_graph.ainvoke()` sequencialmente.

**Exemplo:**

```bash
curl -X POST http://localhost:8000/run \
  -H "X-API-Key: $API_SECRET_KEY"
```

---

## `POST /run-email`

Dispara o grafo de email (`compiled_email_graph`) em thread separada para um cliente.

**Request body:**

```json
{
  "client_id": "uuid-do-cliente-em-clients",
  "list_id": 42,
  "context": "Promoção de inverno com foco em casacos"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `client_id` | `string` | Sim | UUID em `public.clients` |
| `list_id` | `integer` | Sim | ID da lista de contatos no Brevo |
| `context` | `string` | Não | Contexto extra para pesquisador/copywriter |

**Response `200`:**

```json
{
  "status": "started",
  "client_id": "uuid-do-cliente",
  "timestamp": "2026-06-13T15:00:00+00:00"
}
```

**Erros:**

| Status | Causa |
|--------|-------|
| `404` | Cliente não encontrado |
| `403` | API key inválida |

**Exemplo:**

```bash
curl -X POST http://localhost:8000/run-email \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "550e8400-e29b-41d4-a716-446655440000",
    "list_id": 42,
    "context": "Lançamento coleção verão"
  }'
```

---

## Estados de uma decisão

| `executed` | `approved_at` | `approved_by` | Significado |
|------------|---------------|---------------|-------------|
| `false` | `null` | `null` | Pendente — aparece em `GET /decisions` |
| `true` | preenchido | email ou `"autonomous"` | Aprovada e executada |
| `false` | preenchido | `"rejected:..."` | Rejeitada |

---

## CORS e erros globais

- **CORS:** origens de `API_ALLOWED_ORIGINS` (comma-separated).
- **`ValueError`:** retorna `422` com `{"detail": "..."}`.

## Links

- [agent.md](./agent.md) — o que `/run` executa internamente
- [integrations.md](./integrations.md) — APIs chamadas no approve
- [architecture.md](./architecture.md) — fluxo n8n → WhatsApp
