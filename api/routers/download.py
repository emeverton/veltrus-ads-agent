"""
api/routers/download.py — Plugin de download do projeto completo

GET /download/project   → ZIP com todos os arquivos + DOCUMENTACAO.md gerado
GET /download/manifest  → JSON com lista de arquivos incluídos no export

Requer header X-API-Key para autenticação.
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader

from agent.config import settings

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/download", tags=["download"])

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def _require_api_key(key: str = Security(_api_key_header)) -> str:
    if key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


# ---------------------------------------------------------------------------
# Padrões de exclusão (relativo à raiz do projeto)
# ---------------------------------------------------------------------------
_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".next",
    ".cache",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "*.egg-info",
}

_EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dylib",
    ".dll",
    ".log",
    ".tmp",
    ".DS_Store",
}

_EXCLUDE_FILES = {
    ".env",          # nunca incluir segredos reais
    ".env.local",
    ".env.production",
}

# Tamanho máximo por arquivo para evitar binários grandes
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB


def _should_include(path: Path, root: Path) -> bool:
    """Retorna True se o arquivo deve ser incluído no ZIP."""
    # Checar partes do caminho relativo
    rel = path.relative_to(root)
    parts = rel.parts

    for part in parts[:-1]:  # diretórios intermediários
        if part in _EXCLUDE_DIRS or part.endswith(".egg-info"):
            return False

    filename = path.name
    if filename in _EXCLUDE_FILES:
        return False
    if path.suffix in _EXCLUDE_EXTENSIONS:
        return False
    if path.stat().st_size > _MAX_FILE_BYTES:
        return False
    return True


def _collect_files(root: Path) -> list[Path]:
    """Coleta todos os arquivos elegíveis recursivamente."""
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and _should_include(p, root):
            files.append(p)
    return files


# ---------------------------------------------------------------------------
# Geração do documento de documentação
# ---------------------------------------------------------------------------
def _build_documentation(root: Path, collected: list[Path]) -> str:
    """Gera DOCUMENTACAO.md completo com tudo implementado no projeto."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    file_list = "\n".join(f"- `{p.relative_to(root)}`" for p in collected)

    doc = f"""# Veltrus Ads Agent — Documentação Completa

> Gerado automaticamente em {now}

---

## 1. Visão Geral

**Veltrus Ads Agent** é um sistema autônomo de gestão de campanhas publicitárias (Meta Ads e Google Ads)
com capacidade de email marketing (Brevo). Utiliza LangGraph + Claude para tomar decisões e executar
otimizações automaticamente, com alça de controle humano (human-in-the-loop) via API e webhook.

---

## 2. Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Agente / Grafo | Python 3.12 · LangGraph · LangChain Anthropic |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) |
| API REST | FastAPI · Uvicorn |
| Banco de Dados | Supabase (PostgreSQL) · pgvector |
| Meta Ads | `facebook-business` SDK |
| Google Ads | `google-ads` SDK |
| Email | Brevo REST API |
| Agendamento | APScheduler |
| Proxy / TLS | Caddy |
| Deploy | Docker · Docker Compose · Railway |
| Frontend (planejado) | Next.js 14 · shadcn/ui · TanStack Query |

---

## 3. Arquitetura Multi-Agente

```
APScheduler (agent/main.py)
  └── agent/run.py
        ├── Ads Graph (agent/graph.py)          ← Meta + Google
        └── Email Graph (agent/email_graph.py)  ← Brevo

FastAPI (api/main.py)
  ├── GET/PATCH  /decisions     ← aprovação humana
  ├── POST       /run           ← disparo manual do ciclo de ads
  ├── POST       /run-email     ← disparo manual do ciclo de email
  └── GET        /download/*    ← este plugin
```

### 3.1 Ads Graph — 5 nós LangGraph

```
START → analista ──(anomalias)──→ estrategista → revisor → executor → memorizador → END
                └─(sem anomalias)──────────────────────────────────→ memorizador → END
```

| Nó | Função | Ferramentas |
|----|--------|-------------|
| **analista** | Coleta métricas 7d e detecta anomalias (cpa_spike, roas_negative, ctr_drop) | `fetch_account_campaigns`, `fetch_daily_metrics`, `fetch_meta_campaigns_live`, `fetch_meta_insights_live` |
| **estrategista** | Decide ação usando histórico de memória | `search_agent_memory` |
| **revisor** | Classifica risco: LOW / MEDIUM / HIGH | — |
| **executor** | Executa via API ou enfileira para humano | `save_decision`, `run_meta_action`, `run_google_action`, `notify_human` |
| **memorizador** | Persiste aprendizados em `agent_memory` | `save_memory` |

**Roteamento condicional:** se `anomalies == []` → salta direto para `memorizador`.

### 3.2 Email Graph — 6 nós LangGraph

```
START → pesquisador → analista_de_lista → copywriter → otimizador → executor → analista_de_resultados → END
```

| Nó | Função |
|----|--------|
| **pesquisador** | Web search via Anthropic tool nativa (tendências + concorrentes) |
| **analista_de_lista** | Analisa lista Brevo, segmento ideal, melhor horário de envio |
| **copywriter** | Gera 3 variações de subject + preheader + HTML body |
| **otimizador** | Escolhe melhor subject, agenda horário de envio |
| **executor** | Cria campanha no Brevo e salva em `email_campaigns` |
| **analista_de_resultados** | Lê métricas pós-envio e salva memória |

---

## 4. Schema do Banco de Dados (Supabase / PostgreSQL)

### Migration 001 — Schema Inicial

| Tabela | Descrição |
|--------|-----------|
| `clients` | Clientes da Veltrus com `business_dna` JSONB (briefing, tom de voz) |
| `ad_accounts` | Contas de ads (Meta / Google) com token criptografado |
| `campaigns` | Campanhas monitoradas com status e budget diário |
| `daily_metrics` | Métricas diárias normalizadas (spend, CPA, ROAS, CTR, `raw_payload`) |
| `agent_decisions` | Histórico de decisões do agente com raciocínio completo |
| `agent_memory` | Memória semântica com embedding pgvector (1536 dims) + índice HNSW |

### Migration 002 — Campos Normalizados

Adiciona `attribution_window` e `confidence_score` em `daily_metrics` para rastreabilidade
de janela de atribuição e confiança nos dados de conversão.

### Migration 003 — Kill Switch Log

Tabela `kill_switch_log` para auditoria de todas as ações de pausa emergencial de contas,
com `triggered_by`, `reason` e `accounts_paused`.

### Migration 004 — Email Campaigns

Tabela `email_campaigns` para campanha de email marketing Brevo, com variantes de subject,
métricas de abertura/clique/bounce e data de envio.

---

## 5. API REST

### Autenticação

Todas as rotas (exceto `/health`) exigem `X-API-Key: <API_SECRET_KEY>` no header.

### Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Status da API |
| `GET` | `/decisions` | Lista decisões pendentes de aprovação |
| `PATCH` | `/decisions/{id}/approve` | Aprova e executa decisão via Meta/Google API |
| `PATCH` | `/decisions/{id}/reject` | Rejeita com motivo |
| `POST` | `/run` | Dispara ciclo de ads em background |
| `POST` | `/run-email` | Dispara ciclo de email em background |
| `GET` | `/download/project` | **Download ZIP completo do projeto** |
| `GET` | `/download/manifest` | Lista de arquivos no export |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |

### Fluxo de Aprovação Humana

```
Agente detecta anomalia HIGH/MEDIUM
  → save_decision(executed=false)
  → notify_human → n8n webhook → WhatsApp
  → Humano chama PATCH /decisions/{id}/approve
  → Executa ação via Meta/Google API
  → Atualiza approved_by + approved_at
```

---

## 6. Ferramentas (agent/tools/)

### `supabase_client.py`
Cliente Supabase singleton via `service_role` key. Usado por todos os nós para
leitura/escrita de campanhas, métricas, decisões e memória.

### `normalizer.py`
Converte payloads de diferentes fontes (Meta API, Google API, dados de seed) para o
**Unified Marketing Schema** com campos:
`spend_usd`, `impressions`, `clicks`, `conversions_click`, `conversions_view`,
`revenue_usd`, `cpa_click`, `roas_click`, `ctr`, `attribution_window`, `confidence_score`.

### `meta_ads.py`
Wrapper assíncrono para `facebook-business` SDK:
- `list_campaigns` — lista campanhas da conta
- `get_campaign_insights` — métricas de performance
- `pause_campaign` / `activate_campaign`
- `update_campaign_budget`

### `google_ads.py`
Wrapper assíncrono para `google-ads` SDK com OAuth2:
- `list_campaigns`
- `get_campaign_metrics`
- `pause_campaign` / `activate_campaign`
- `update_campaign_budget`

### `email_brevo.py`
Wrapper para Brevo REST API:
- Gestão de listas e contatos
- Criação e envio de campanhas de email
- Leitura de estatísticas pós-envio

---

## 7. Variáveis de Ambiente

Veja `.env.example` para a lista completa. Nunca commitar `.env`.

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | ✅ | API key do Claude |
| `SUPABASE_URL` | ✅ | URL do projeto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Chave admin do Supabase |
| `API_SECRET_KEY` | ✅ | Chave de autenticação da API REST |
| `META_ACCESS_TOKEN` | — | Token da Meta Ads API |
| `META_AD_ACCOUNT_ID` | — | ID da conta de anúncios Meta |
| `GOOGLE_ADS_*` | — | Credenciais Google Ads OAuth2 |
| `BREVO_API_KEY` | — | Chave API Brevo (email) |
| `AGENT_AUTONOMOUS_MODE` | — | `false` em dev; `true` habilita execução sem aprovação |
| `AGENT_MAX_DAILY_SPEND_USD` | — | Teto de gasto diário (proteção financeira) |
| `N8N_WEBHOOK_URL` | — | Webhook n8n para notificações WhatsApp |
| `NOTIFY_PHONE_NUMBER` | — | Número E.164 para alertas |

---

## 8. Deploy

### Docker Compose (produção)
```
docker compose up -d
```
Serviços: `api` (FastAPI na 8000), `agent` (APScheduler), `caddy` (TLS reverse proxy).

### Railway
```
railway up
```
`railway.json` configura build e start commands automaticamente.

### Scripts auxiliares
| Script | Função |
|--------|--------|
| `scripts/setup.sh` | Instala dependências no servidor VPS |
| `scripts/deploy.sh` | Deploy local → VPS via Docker |
| `scripts/remote_deploy.sh` | Deploy remoto via SSH/rsync |
| `scripts/seed_test_data.py` | Popula Supabase com dados de teste |
| `scripts/kill_switch.py` | Pausa emergencial de todas as campanhas ativas |
| `scripts/export_project.py` | Gera ZIP do projeto para download local |

---

## 9. Segurança

- Todas as ações destrutivas requerem `AGENT_AUTONOMOUS_MODE=true` OU aprovação humana explícita
- Tokens Meta/Google armazenados em `ad_accounts.token` — nunca expostos via anon key
- RLS habilitado em todas as tabelas do Supabase (deny-by-default)
- `API_SECRET_KEY` validado via header `X-API-Key` em todos os endpoints sensíveis
- Kill switch (`scripts/kill_switch.py`) registra todas as ações em `kill_switch_log`

---

## 10. Arquivos do Projeto

Total de arquivos incluídos neste export:

{file_list}

---

## 11. Próximos Passos

- [ ] Dashboard Next.js — pages, components, API client (`dashboard/app/`)
- [ ] Supervisor pattern com grafos separados por plataforma (`agent/graphs/`)
- [ ] Vector similarity search para `agent_memory` (substituir ilike text search)
- [ ] Testes automatizados (`tests/`)
- [ ] Políticas RLS para acesso de leitura autenticado no dashboard
- [ ] WebSocket endpoint para streaming de status do agente em tempo real
- [ ] Separação de `agent/nodes/`, `agent/prompts/`, `api/models/`

---

*Documentação gerada pelo plugin `GET /download/project` — Veltrus Ads Agent v0.1.0*
"""
    return doc


# ---------------------------------------------------------------------------
# GET /download/manifest
# ---------------------------------------------------------------------------
@router.get("/manifest", summary="Lista arquivos incluídos no export")
async def get_manifest(
    _key: str = Depends(_require_api_key),
) -> dict[str, Any]:
    """Retorna a lista de arquivos que serão incluídos no download do projeto."""
    root = Path(__file__).resolve().parents[2]  # /workspace
    collected = _collect_files(root)

    files = []
    total_bytes = 0
    for p in collected:
        size = p.stat().st_size
        total_bytes += size
        files.append({
            "path": str(p.relative_to(root)),
            "size_bytes": size,
        })

    log.info("download.manifest", total_files=len(files), total_bytes=total_bytes)
    return {
        "total_files": len(files),
        "total_size_bytes": total_bytes,
        "total_size_kb": round(total_bytes / 1024, 1),
        "files": files,
    }


# ---------------------------------------------------------------------------
# GET /download/project
# ---------------------------------------------------------------------------
@router.get(
    "/project",
    summary="Download ZIP completo do projeto",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Arquivo ZIP com todo o código-fonte e documentação.",
        }
    },
)
async def download_project(
    _key: str = Depends(_require_api_key),
) -> StreamingResponse:
    """
    Gera e retorna um ZIP com:
    - Todos os arquivos do projeto (exceto .env, .venv, __pycache__, node_modules, .git)
    - DOCUMENTACAO.md gerado automaticamente com arquitetura, schema, API e instruções
    """
    root = Path(__file__).resolve().parents[2]  # /workspace
    collected = _collect_files(root)

    log.info("download.start", total_files=len(collected), root=str(root))

    # Cria o ZIP em memória
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1) Adiciona todos os arquivos do projeto
        for file_path in collected:
            archive_name = str(file_path.relative_to(root))
            try:
                zf.write(file_path, arcname=archive_name)
            except Exception as exc:
                log.warning("download.skip_file", path=archive_name, error=str(exc))
                continue

        # 2) Adiciona DOCUMENTACAO.md gerado
        doc_content = _build_documentation(root, collected)
        zf.writestr("DOCUMENTACAO.md", doc_content.encode("utf-8"))

        # 3) Adiciona um manifesto de export
        manifest_lines = [
            f"# Export Manifest — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"# Total de arquivos: {len(collected)}",
            "",
        ] + [str(p.relative_to(root)) for p in collected] + ["DOCUMENTACAO.md"]
        zf.writestr("EXPORT_MANIFEST.txt", "\n".join(manifest_lines))

    zip_buffer.seek(0)
    zip_size = zip_buffer.getbuffer().nbytes

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"veltrus-ads-agent_{timestamp}.zip"

    log.info("download.ready", filename=filename, zip_size_bytes=zip_size)

    return StreamingResponse(
        content=zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(zip_size),
            "X-Files-Count": str(len(collected)),
        },
    )
