# Guardrails — Regras de Segurança do Agente

O sistema possui duas camadas de proteção financeira independentes: os **guardrails do agente** (LangGraph) e o **kill switch** (script cron independente do LLM).

---

## Visão Geral das Camadas

```
┌─────────────────────────────────────────────────────────────┐
│  CAMADA 1: Guardrails do Agente LangGraph                   │
│                                                              │
│  - REVISOR classifica risco: LOW / MEDIUM / HIGH            │
│  - EXECUTOR decide executar ou pedir aprovação humana       │
│  - Limites configuráveis: max_budget_change_pct,            │
│    max_daily_spend_usd, autonomous_mode                     │
│  - Aplica-se a CADA decisão individualmente                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  CAMADA 2: Kill Switch (scripts/kill_switch.py)             │
│                                                              │
│  - Script independente — NÃO usa LLM                        │
│  - Roda a cada hora via cron                                 │
│  - Verifica 3 regras hardcoded por campanha                 │
│  - Pausa campanhas em emergência diretamente via API        │
│  - Registra todas as ações em kill_switch_log               │
└─────────────────────────────────────────────────────────────┘
```

---

## Camada 1: Guardrails do Agente LangGraph

### Variável: `AGENT_AUTONOMOUS_MODE`

A variável mais crítica do sistema. Controla se o agente executa ações diretamente via API ou enfileira para aprovação humana.

| Valor | Comportamento |
|-------|--------------|
| `false` (padrão) | **Modo supervisionado.** Nenhuma ação é executada sem aprovação humana, independentemente do nível de risco. Todas as decisões são salvas em `agent_decisions` com `executed=false` e notificação enviada via WhatsApp. |
| `true` | **Modo autônomo.** Ações classificadas como `LOW` são executadas diretamente. `MEDIUM` e `HIGH` ainda requerem aprovação humana. |

**Segurança:** `AGENT_AUTONOMOUS_MODE=true` deve ser ativado apenas após validação completa em ambiente de staging. Recomenda-se manter `false` indefinidamente para contas com alto volume de spend.

### Variável: `AGENT_MAX_DAILY_SPEND_USD`

**Padrão:** `500.0`

Limite de gasto diário por conta de anúncios em USD. Usado como contexto nos prompts do ESTRATEGISTA e REVISOR para calibrar a severidade das decisões. **Não é aplicado como hardstop pelo agente** — serve como referência para a classificação de risco.

O kill switch aplica verificação de spend como hardstop real (ver Camada 2).

### Variável: `AGENT_MAX_BUDGET_CHANGE_PCT`

**Padrão:** `20.0`

Percentual máximo de alteração de budget permitido por ciclo. Passado como contexto ao ESTRATEGISTA:

```python
user_prompt = f"""
Limites configurados:
- Mudança máxima de budget por ciclo: {settings.agent_max_budget_change_pct}%
- Limite de gasto diário: ${settings.agent_max_daily_spend_usd}
"""
```

O LLM usa esse limite como referência — não é um check de código. A validação real é feita pela classificação de risco no REVISOR.

### Classificação de Risco (Nó REVISOR)

O REVISOR aplica critérios determinísticos para classificar o risco de cada decisão:

| Nível | Critério | Ação do EXECUTOR |
|-------|----------|-----------------|
| `HIGH` | `pause_campaign` com `last_spend > $100` OU qualquer mudança de budget > 20% com spend > $200/dia | Salva como pendente + notifica humano |
| `MEDIUM` | `pause_campaign` com spend $50–$100 OU mudança > 20% (qualquer spend) OU `budget_decrease` > 30% | Salva como pendente + notifica humano |
| `LOW` | Qualquer outra ação, incluindo `monitor_only` | Executa via API (se `autonomous_mode=true`) OU salva + notifica (se `false`) |

### Lógica de Execução (Nó EXECUTOR)

```
SE risk_level == LOW E autonomous_mode == true:
    → Executa ação via API (run_meta_action ou run_google_action)
    → save_decision(executed=true, approved_by="autonomous")

SE risk_level == LOW E autonomous_mode == false:
    → save_decision(executed=false)
    → notify_human() → n8n → WhatsApp

SE risk_level == MEDIUM ou HIGH (sempre):
    → save_decision(executed=false)
    → notify_human() → n8n → WhatsApp
```

---

## Camada 2: Kill Switch

**Arquivo:** `scripts/kill_switch.py`  
**Execução:** Cron a cada hora — **completamente independente do LangGraph e do LLM**  
**Banco:** Registra todas as ações em `kill_switch_log`

### As 3 Regras

#### Regra 1: `spend_overage`

```python
SPEND_MULT = 1.1  # gasto > budget × 1.1 dispara

if daily_budget > 0 and spend_today > daily_budget * SPEND_MULT:
    # → pausa campanha + log
```

| Campo | Valor |
|-------|-------|
| Condição | Gasto do dia atual > `daily_budget × 1.1` |
| Threshold | `daily_budget` da tabela `campaigns` |
| Ação | **Pausa a campanha** via API (Meta ou Google) |
| Log | `trigger_type = "spend_overage"`, `action_taken = "paused"` |

#### Regra 2: `cpa_spike`

```python
CPA_MULT = 2.0  # cpa > cpa_max × 2.0 dispara

if cpa_max and cpa_today and cpa_today > cpa_max * CPA_MULT:
    # → pausa campanha + log
```

| Campo | Valor |
|-------|-------|
| Condição | CPA de hoje > `cpa_max × 2.0` |
| Fonte do `cpa_max` | Campo `business_dna.objetivo_principal` do cliente |
| Extração | Regex: `r"cpa\s*[<abaixode\s]*\$?\s*(\d+(?:\.\d+)?)"` (ex: `"CPA < $25"` → 25.0) |
| Ação | **Pausa a campanha** via API |
| Log | `trigger_type = "cpa_spike"`, `action_taken = "paused"` |

**Exemplo de `business_dna.objetivo_principal` que define `cpa_max`:**
```json
{
  "objetivo_principal": "maximizar ROAS mantendo CPA < $25"
}
```

Se `business_dna.objetivo_principal` não contiver um valor de CPA reconhecível, `cpa_max` retorna `None` e a regra é pulada.

#### Regra 3: `roas_critical`

```python
ROAS_MIN = 0.5  # roas < 0.5 dispara alerta (sem pausa)

if roas_today is not None and roas_today < ROAS_MIN:
    # → apenas alerta + log (não pausa)
```

| Campo | Valor |
|-------|-------|
| Condição | ROAS de hoje < 0.5 |
| Ação | **Apenas registra alerta** em `kill_switch_log` — NÃO pausa a campanha |
| Log | `trigger_type = "roas_critical"`, `action_taken = "alerted"` |

### Fonte dos Dados de Hoje

O kill switch lê as métricas do **Supabase** (tabela `daily_metrics`) para a data de hoje:

```python
metrics_resp = (
    supabase.table("daily_metrics")
    .select("spend, cpa, roas, conversions, confidence_score, cpa_click:cpa, roas_click:roas")
    .eq("campaign_id", camp_id)
    .eq("date", today)
    .maybe_single()
    .execute()
)
```

Se não houver dados de hoje para a campanha, nenhuma regra é verificada.

### Modo `--dry-run`

```bash
# Simula sem executar ações ou chamar APIs externas
PYTHONPATH=. python scripts/kill_switch.py --dry-run
```

Em modo `dry-run`:
- Nenhuma API de ads é chamada
- As verificações são realizadas normalmente
- `action_taken` é registrado como `"dry_run"` em `kill_switch_log`

### Outcomes das ações

| `action_taken` | Significado |
|---------------|-------------|
| `"paused"` | Campanha pausada com sucesso via API |
| `"alerted"` | Alerta registrado (apenas `roas_critical`) — sem pausa |
| `"pause_failed"` | Tentativa de pausa falhou (erro na API) |
| `"dry_run"` | Modo simulação — nenhuma ação real |

### Execução Manual

```bash
# Modo real
PYTHONPATH=. python scripts/kill_switch.py

# Simulação
PYTHONPATH=. python scripts/kill_switch.py --dry-run

# Verificar log no Supabase
# SELECT * FROM kill_switch_log ORDER BY created_at DESC LIMIT 20;
```

### Cron (recomendado: a cada hora)

```cron
# Adicionar com: crontab -e
0 * * * * cd /app && PYTHONPATH=. python scripts/kill_switch.py >> /var/log/kill_switch.log 2>&1
```

---

## Logs de Segurança

O kill switch usa `structlog` com nível `CRITICAL` para eventos de disparo:

```
kill_switch.spend_overage   → campanha pausada por overspend
kill_switch.cpa_spike       → campanha pausada por CPA spike
kill_switch.roas_critical   → alerta de ROAS crítico
kill_switch.pause_failed    → falha ao pausar (verificar token/credenciais)
```

O histórico auditável completo está em `public.kill_switch_log`.

---

## Configuração por Cliente

Os guardrails são configurados em dois níveis:

### Nível global (variáveis de ambiente)

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `AGENT_AUTONOMOUS_MODE` | `false` | Ativa execução autônoma de ações LOW |
| `AGENT_MAX_DAILY_SPEND_USD` | `500.0` | Referência de spend máximo diário por conta |
| `AGENT_MAX_BUDGET_CHANGE_PCT` | `20.0` | Percentual máximo de ajuste de budget por ciclo |

### Nível por cliente (campo `business_dna` no Supabase)

| Campo | Uso |
|-------|-----|
| `objetivo_principal` | Parseado pelo kill switch para extrair `cpa_max` (ex: `"CPA < $25"`) |
| Demais campos | Contexto para o ESTRATEGISTA decidir ações mais alinhadas ao negócio |

**Exemplo de `business_dna` bem configurado:**
```json
{
  "objetivo_principal": "maximizar ROAS mantendo CPA < $30",
  "vertical": "ecommerce de moda",
  "tom_de_voz": "aspiracional e premium",
  "restricoes": [
    "não pausar campanhas em datas comemorativas sem aprovação",
    "budget mínimo de $50/dia por campanha"
  ],
  "sazonalidade": "picos em novembro (Black Friday) e dezembro (Natal)"
}
```

---

## Resumo das Proteções

| Proteção | Nível | Mecanismo | Quando ativa |
|----------|-------|-----------|--------------|
| `autonomous_mode=false` | Global | Todas as decisões exigem aprovação humana | Sempre que `AGENT_AUTONOMOUS_MODE=false` |
| Classificação de risco MEDIUM/HIGH | Por decisão | REVISOR bloqueia execução autônoma | Quando a decisão é riscosa |
| `max_budget_change_pct` | Por ciclo | Contexto para o LLM | Passado como instrução ao ESTRATEGISTA |
| `max_daily_spend_usd` | Por conta | Referência de risco | Passado como instrução ao REVISOR |
| `spend_overage` kill switch | Por campanha | Script independente, cron 1h | Quando spend > budget × 1.1 |
| `cpa_spike` kill switch | Por campanha | Script independente, cron 1h | Quando CPA > cpa_max × 2.0 |
| `roas_critical` kill switch | Por campanha | Alerta (sem pausa), cron 1h | Quando ROAS < 0.5 |
| Auditoria completa | Sistema | `agent_decisions` + `kill_switch_log` | Sempre |
