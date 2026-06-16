# Veltrus Ads Agent — Plugin MCP

Expõe o **Veltrus Ads Agent** como um servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io),
permitindo plugar o agente em qualquer cliente MCP (Cursor, Claude Desktop, etc.).

O plugin é um cliente fino sobre a API FastAPI do agente — ele **não duplica**
nenhuma lógica de negócio. Toda a persistência no Supabase, execução de ações via
Meta/Google na aprovação e os ciclos LangGraph continuam na API e são reaproveitados.

## Ferramentas expostas

| Ferramenta | O que faz | Endpoint da API |
|---|---|---|
| `check_health` | Verifica se a API está acessível e saudável | `GET /health` |
| `list_pending_decisions` | Lista decisões do agente aguardando aprovação humana | `GET /decisions` |
| `approve_decision` | Aprova e executa uma decisão (ação real na plataforma) | `PATCH /decisions/{id}/approve` |
| `reject_decision` | Rejeita uma decisão (sem ação externa) | `PATCH /decisions/{id}/reject` |
| `trigger_agent_run` | Dispara um ciclo de análise para todas as contas ativas | `POST /run` |
| `trigger_email_campaign` | Dispara o agente de email marketing para um cliente | `POST /run-email` |

## Configuração

Variáveis de ambiente (também lidas do `.env` na raiz do repo, se existir):

| Variável | Padrão | Descrição |
|---|---|---|
| `VELTRUS_API_URL` | `http://localhost:8000` | URL base da API do agente |
| `VELTRUS_API_KEY` | (usa `API_SECRET_KEY`) | Chave para o header `X-API-Key` |
| `VELTRUS_TIMEOUT` | `30` | Timeout por requisição (segundos) |

## Pré-requisitos

A API do agente precisa estar rodando (o plugin fala com ela por HTTP):

```bash
PYTHONPATH=. uvicorn api.main:app --reload --port 8000
```

## Executar o servidor MCP

```bash
# via stdio (forma padrão de integração com clientes MCP)
PYTHONPATH=. python -m plugins.veltrus_mcp.server
```

## Registrar no Cursor

Adicione ao `~/.cursor/mcp.json` (ou ao `.cursor/mcp.json` do projeto):

```json
{
  "mcpServers": {
    "veltrus-ads-agent": {
      "command": "python",
      "args": ["-m", "plugins.veltrus_mcp.server"],
      "cwd": "/caminho/para/veltrus-ads-agent",
      "env": {
        "PYTHONPATH": "/caminho/para/veltrus-ads-agent",
        "VELTRUS_API_URL": "http://localhost:8000",
        "VELTRUS_API_KEY": "sua-API_SECRET_KEY"
      }
    }
  }
}
```

> Dica: use o Python da venv do projeto (`venv/bin/python`) no campo `command`
> para garantir que a dependência `mcp` esteja disponível.

## Registrar no Claude Desktop

No `claude_desktop_config.json`, use o mesmo formato de `mcpServers` acima.

## Exemplo de uso (linguagem natural no cliente)

- "Liste as decisões pendentes do agente de ads."
- "Aprove a decisão `<id>` em nome de joao@empresa.com."
- "Rejeite a decisão `<id>` porque o budget já foi ajustado manualmente."
- "Dispare um ciclo de análise do agente agora."
