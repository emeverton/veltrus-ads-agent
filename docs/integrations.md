# Integrações — Veltrus Ads Agent

Documentação técnica de cada integração externa, incluindo como funcionam, as operações suportadas e detalhes de implementação.

---

## Meta Ads API

**Arquivo:** `agent/tools/meta_ads.py`  
**SDK:** `facebook-business >= 21.0.0`  
**Versão da API:** `v21.0` (configurável via `META_API_VERSION`)

### Como funciona

O agente usa o SDK oficial `facebook-business` para interagir com a Meta Marketing API. A autenticação é feita por access token por conta (armazenado em `ad_accounts.token`). O SDK é inicializado por chamada via `FacebookAdsApi.init(access_token=token, api_version=version)`.

### Operações implementadas

| Função | Método SDK | Descrição |
|--------|------------|-----------|
| `get_ad_accounts(access_token)` | `User("me").get_ad_accounts()` | Lista todas as contas acessíveis pelo token |
| `list_campaigns(account_id, access_token)` | `AdAccount.get_campaigns()` | Campanhas ACTIVE e PAUSED em tempo real |
| `get_campaign_insights(account_id, campaign_id, date_start, date_end, access_token)` | `AdAccount.get_insights()` | Métricas agregadas do período |
| `update_campaign_budget(campaign_id, daily_budget, access_token)` | `Campaign.remote_update(daily_budget=cents)` | Atualiza budget (valor em centavos internamente) |
| `pause_campaign(campaign_id, access_token)` | `Campaign.remote_update(status=PAUSED)` | Pausa campanha ativa |
| `activate_campaign(campaign_id, access_token)` | `Campaign.remote_update(status=ACTIVE)` | Ativa campanha pausada |

### Campos de insights coletados

```python
_INSIGHT_FIELDS = [
    "spend",
    "impressions",
    "clicks",
    "actions",           # conversões por tipo (purchase, lead, etc.)
    "action_values",     # receita por tipo de ação → base do ROAS
    "cost_per_action_type",
    "ctr",
]
```

**Tipos de conversão reconhecidos:**
```python
_CONVERSION_ACTION_TYPES = {"purchase", "lead", "complete_registration", "subscribe"}
```

### Parâmetros de insights

```python
params = {
    "level": "campaign",
    "filtering": [{"field": "campaign.id", "operator": "EQUAL", "value": campaign_id}],
    "time_range": {"since": "2026-06-01", "until": "2026-06-07"},
    "time_increment": "all_days",  # agrega o período em uma linha
}
```

### Retry com backoff exponencial

Erros de rate limit (códigos `17`, `613`, `80004`) são retentados até 3 vezes com backoff de `2^attempt` segundos:

```python
_RATE_LIMIT_CODES = {17, 613, 80004}
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # segundos
```

### Variáveis de ambiente necessárias

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `META_APP_ID` | não (para autenticação OAuth) | App ID da Meta |
| `META_APP_SECRET` | não | App Secret |
| `META_ACCESS_TOKEN` | não (token padrão) | Token de acesso padrão |
| `META_AD_ACCOUNT_ID` | não | ID da conta padrão (ex: `act_123456789`) |
| `META_API_VERSION` | não (padrão: `v21.0`) | Versão da API |

Os tokens por conta são armazenados em `ad_accounts.token` no Supabase e buscados em tempo de execução.

---

## Google Ads API

**Arquivo:** `agent/tools/google_ads.py`  
**SDK:** `google-ads >= 25.0.0`  
**Linguagem de query:** GAQL (Google Ads Query Language)

### Como funciona

O agente usa o cliente Python oficial `google-ads`. Credenciais OAuth por conta (refresh token) são armazenadas em `ad_accounts.token` e combinadas com as credenciais da aplicação (`client_id`, `client_secret`, `developer_token`) em tempo de execução via `GoogleAdsClient.load_from_dict()`.

### Operações implementadas

| Função | Serviço gRPC | Operação | Descrição |
|--------|-------------|----------|-----------|
| `get_campaigns(customer_id, credentials)` | `GoogleAdsService` | `search()` (GAQL) | Lista campanhas não-removidas |
| `get_campaign_insights(customer_id, campaign_id, date_start, date_end, credentials)` | `GoogleAdsService` | `search()` (GAQL) | Métricas agregadas do período |
| `update_campaign_budget(customer_id, campaign_budget_id, amount_micros, credentials)` | `CampaignBudgetService` | `mutate_campaign_budgets()` | Atualiza budget (em micros) |
| `pause_campaign(customer_id, campaign_id, credentials)` | `CampaignService` | `mutate_campaigns()` | Status → PAUSED |
| `activate_campaign(customer_id, campaign_id, credentials)` | `CampaignService` | `mutate_campaigns()` | Status → ENABLED |

### Queries GAQL

**Listar campanhas:**
```sql
SELECT
    campaign.id,
    campaign.name,
    campaign.status,
    campaign_budget.id,
    campaign_budget.amount_micros
FROM campaign
WHERE campaign.status != 'REMOVED'
ORDER BY campaign.name
```

**Métricas por período:**
```sql
SELECT
    campaign.id,
    metrics.cost_micros,
    metrics.impressions,
    metrics.clicks,
    metrics.conversions,
    metrics.conversions_value
FROM campaign
WHERE campaign.id = {campaign_id}
  AND segments.date BETWEEN '{date_start}' AND '{date_end}'
```

### Valores em micros

O Google Ads API usa **micros** (USD × 1.000.000) para budgets:
```python
amount_micros = int(daily_budget_usd * 1_000_000)
# Ex: $10/dia → 10_000_000 micros
```

### Retry com backoff exponencial

Erros retentáveis: `grpc.StatusCode.RESOURCE_EXHAUSTED` e `grpc.StatusCode.UNAVAILABLE` (até 3 tentativas).

### Variáveis de ambiente necessárias

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | **sim** | Token de desenvolvedor da conta MCC |
| `GOOGLE_ADS_CLIENT_ID` | **sim** | OAuth client ID da aplicação |
| `GOOGLE_ADS_CLIENT_SECRET` | **sim** | OAuth client secret |
| `GOOGLE_ADS_REFRESH_TOKEN` | não (token padrão) | Refresh token padrão |
| `GOOGLE_ADS_CUSTOMER_ID` | não | Customer ID padrão |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | não | MCC ID (se aplicável) |

---

## Evolution API — WhatsApp Business

A Evolution API é usada como intermediária entre o n8n e o WhatsApp Business Cloud API. O n8n formata e envia a mensagem interativa via Evolution API, que gerencia a sessão WhatsApp.

### Como funciona no fluxo de aprovação

```
Agente → notify_human() → POST N8N_WEBHOOK_URL
  → n8n Workflow
    → Evolution API POST /message/sendButtons
      → WhatsApp Business (mensagem com botões ✅/❌)
    → Usuário responde
  → Evolution API webhook → n8n (botão clicado)
  → n8n → PATCH /decisions/{id}/approve ou /reject
```

### Payload enviado pelo agente ao n8n

```json
{
  "decision_id":   "uuid-da-decisao",
  "campaign_name": "Campanha Black Friday",
  "action_type":   "budget_increase",
  "risk_level":    "MEDIUM",
  "reasoning":     "ROAS 3.8x, CPA dentro do limite. Recomendo +15% budget.",
  "phone_number":  "5511999998888"
}
```

### Configuração no n8n

O n8n recebe o webhook do agente e usa a Evolution API para enviar mensagem interativa com botões:

**Endpoint Evolution:** `POST https://evo.seudominio.com/message/sendButtons/{instance}`

**Body:**
```json
{
  "number": "5511999998888@s.whatsapp.net",
  "title": "Veltrus Ads Agent — Aprovação Necessária",
  "description": "Campanha: Black Friday\nAção: budget_increase (MEDIUM)\nRaciocínio: ROAS 3.8x...",
  "footer": "ID: uuid-da-decisao",
  "buttons": [
    {"buttonId": "approve_uuid-da-decisao", "buttonText": {"displayText": "✅ Aprovar"}},
    {"buttonId": "reject_uuid-da-decisao",  "buttonText": {"displayText": "❌ Rejeitar"}}
  ]
}
```

### Variáveis de ambiente necessárias

| Variável | Descrição |
|----------|-----------|
| `N8N_WEBHOOK_URL` | URL do webhook n8n (ex: `https://n8n.seudominio.com/webhook/agent-decision`) |
| `NOTIFY_PHONE_NUMBER` | Número WhatsApp no formato E.164 (ex: `5511999998888`) |
| `EVOLUTION_API_KEY` | API key da Evolution API (usado na configuração do Docker) |

**Comportamento sem `N8N_WEBHOOK_URL`:**
```python
# Se N8N_WEBHOOK_URL não estiver configurado, notify_human() apenas loga:
return {
    "notification_sent": False,
    "channel": "log_only",
    "message": "[MEDIUM] Campanha 'X': ação 'budget_increase' aguarda aprovação. ID: uuid"
}
```

---

## n8n — Automação de Workflows

O n8n orquestra o fluxo de aprovação humana: recebe o webhook do agente, envia mensagem WhatsApp e processa a resposta do usuário.

### Workflow de aprovação (estrutura dos nodes)

```
Node 1: Webhook (trigger)
  └── Recebe POST do agente com {decision_id, campaign_name, action_type, risk_level, reasoning, phone_number}

Node 2: HTTP Request → Evolution API
  └── Envia mensagem interativa com botões ✅/❌

Node 3: Webhook (resposta do WhatsApp)
  └── Recebe callback da Evolution API com {button_reply.id}

Node 4: Switch (Aprovar vs Rejeitar)
  └── Condição: button_reply.id.startsWith("approve_") → Branch A
                button_reply.id.startsWith("reject_")  → Branch B

Node 5a: HTTP Request → PATCH /decisions/{id}/approve
  └── X-API-Key: {API_SECRET_KEY}
  └── Body: {"approved_by": "whatsapp:{phone_number}"}

Node 5b: HTTP Request → PATCH /decisions/{id}/reject
  └── X-API-Key: {API_SECRET_KEY}
  └── Body: {"rejected_by": "whatsapp:{phone_number}", "reason": "Rejeitado via WhatsApp"}

Node 6: HTTP Request → Evolution API
  └── Envia mensagem de confirmação ao usuário
```

### Variáveis de ambiente n8n

| Variável | Descrição |
|----------|-----------|
| `N8N_BASIC_AUTH_USER` | Usuário para acesso ao painel n8n |
| `N8N_BASIC_AUTH_PASSWORD` | Senha para acesso ao painel n8n |
| `N8N_ENCRYPTION_KEY` | Chave de criptografia das credenciais n8n |
| `N8N_HOST` | Domínio do n8n (ex: `n8n.seudominio.com`) |
| `WEBHOOK_URL` | URL base para webhooks (ex: `https://n8n.seudominio.com/`) |

---

## Brevo — Email Marketing

**Arquivo:** `agent/tools/email_brevo.py`  
**Integração:** HTTP direto (sem SDK) para a Brevo API v3  
**Base URL:** `https://api.brevo.com/v3`

### Como funciona

O agente usa chamadas HTTP diretas à Brevo API v3 com autenticação via header `api-key`. Todas as chamadas passam por um wrapper `_request()` com retry automático.

### Operações implementadas

| Função | Endpoint | Método | Descrição |
|--------|----------|--------|-----------|
| `get_account_stats(days)` | `/account` + `/emailCampaigns` | GET | Estatísticas agregadas da conta |
| `get_lists()` | `/contacts/lists` | GET (paginado) | Lista todas as listas de contatos |
| `get_campaigns(limit)` | `/emailCampaigns` | GET | Últimas N campanhas com métricas |
| `create_email_campaign(name, subject, html_content, list_id, scheduled_at)` | `/emailCampaigns` | POST | Cria campanha (agendada ou rascunho) |
| `send_campaign(campaign_id)` | `/emailCampaigns/{id}/sendNow` | POST | Dispara imediatamente um rascunho |
| `get_campaign_report(campaign_id)` | `/emailCampaigns/{id}` | GET | Métricas pós-disparo |
| `add_contact(email, name, list_id, attributes)` | `/contacts` | POST | Adiciona/atualiza contato |
| `get_best_send_time(list_id)` | `/emailCampaigns` | GET | Analisa histórico e retorna melhor horário |

### Retry automático

```python
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # segundos
_DEFAULT_TIMEOUT = 30  # segundos
```

### Criar campanha (request body)

```json
{
  "name": "Newsletter Jun/26 - Cliente X",
  "subject": "3 produtos que você não pode perder esse mês",
  "htmlContent": "<!doctype html>...",
  "recipients": {"listIds": [123]},
  "scheduledAt": "2026-06-17T09:00:00Z"
}
```

**Resposta:**
```json
{"id": 456789}
```

### Métricas retornadas por `get_campaign_report`

```python
{
    "campaign_id": 456789,
    "name": "Newsletter Jun/26",
    "subject": "3 produtos...",
    "status": "sent",
    "sent_date": "2026-06-17T09:00:00.000Z",
    "sent": 5000,
    "delivered": 4850,
    "unique_opens": 1210,
    "opens": 1680,
    "unique_clicks": 242,
    "clicks": 310,
    "hard_bounces": 45,
    "soft_bounces": 105,
    "unsubscriptions": 12,
    "complaints": 2,
    "open_rate": 0.249485,
    "click_rate": 0.049897,
    "ctor": 0.200000,     # click-to-open rate
    "bounce_rate": 0.030928,
    "unsubscribe_rate": 0.002474,
    "raw_payload": {...}  # resposta completa para auditoria
}
```

### Inferência do melhor horário (`get_best_send_time`)

Analisa as últimas 100 campanhas enviadas para a lista e retorna o slot `(weekday, hour)` com maior `open_rate` ponderado pelo volume entregue:

```python
{
    "list_id": 123,
    "best_weekday": "tue",
    "best_weekday_index": 1,
    "best_hour": 9,
    "expected_open_rate": 0.283000,
    "weighted_volume": 4850,
    "samples": 12,
    "weekday_distribution": {"tue": 5, "wed": 4, "thu": 3},
    "hour_distribution": {9: 8, 10: 4}
}
```

### Variáveis de ambiente necessárias

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `BREVO_API_KEY` | **sim** | API Key da conta Brevo (`xkeysib-...`) |
| `BREVO_API_BASE_URL` | não (padrão: `https://api.brevo.com/v3`) | Base URL da API |

---

## Resumo de Dependências por Integração

| Integração | Pacote Python | Variáveis obrigatórias |
|-----------|--------------|----------------------|
| Meta Ads | `facebook-business >= 21.0.0` | `META_API_VERSION` + token por conta em `ad_accounts` |
| Google Ads | `google-ads >= 25.0.0`, `google-auth` | `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET` + refresh_token por conta |
| Brevo | `requests` (HTTP direto) | `BREVO_API_KEY` |
| n8n → WhatsApp | — (webhook HTTP) | `N8N_WEBHOOK_URL`, `NOTIFY_PHONE_NUMBER` |
| Anthropic LLM | `langchain-anthropic >= 0.3.0`, `anthropic >= 0.40.0` | `ANTHROPIC_API_KEY` |
| Supabase | `supabase >= 2.9.0`, `postgrest >= 0.17.0` | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
