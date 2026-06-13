#!/usr/bin/env python3
"""
Veltrus Ads Agent — Plugin de Exportação

Gera um pacote ZIP completo com todo o código-fonte, migrations,
documentação detalhada e manifesto de arquivos.

Uso:
    python3 scripts/export_bundle.py
    python3 scripts/export_bundle.py --output ./meu-pacote.zip
    python3 scripts/export_bundle.py --docs-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

EXCLUDE_DIRS = {
    ".git",
    ".claude",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".next",
    "venv",
    ".venv",
    "dist",
    ".mypy_cache",
    ".ruff_cache",
}

EXCLUDE_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ".DS_Store",
}

EXCLUDE_PATTERNS = [
    re.compile(r"\.pyc$"),
    re.compile(r"\.pyo$"),
    re.compile(r"\.zip$"),
]


def _should_include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts

    if any(part in EXCLUDE_DIRS for part in parts):
        return False
    if path.name in EXCLUDE_FILES:
        return False
    if any(p.search(path.name) for p in EXCLUDE_PATTERNS):
        return False
    return True


def _collect_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and _should_include(path):
            files.append(path)
    return files


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _read_safe(path: Path, limit: int = 50_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:limit]
    except OSError:
        return ""


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _git_info() -> dict[str, str]:
    import subprocess

    info: dict[str, str] = {}
    for key, cmd in [
        ("commit", ["git", "rev-parse", "HEAD"]),
        ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        ("date", ["git", "log", "-1", "--format=%ci"]),
        ("message", ["git", "log", "-1", "--format=%s"]),
    ]:
        try:
            result = subprocess.run(
                cmd, cwd=ROOT, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info[key] = result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    return info


def generate_documentation(files: list[Path]) -> str:
    """Gera documentação completa do projeto."""
    git = _git_info()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    py_files = [f for f in files if f.suffix == ".py" and _count_lines(f) > 0]
    sql_files = [f for f in files if f.suffix == ".sql"]
    ts_files = [f for f in files if f.suffix in (".ts", ".tsx") and _count_lines(f) > 0]

    lines: list[str] = [
        "# Veltrus Ads Agent — Documentação Completa do Projeto",
        "",
        f"> Gerado automaticamente em **{now}** pelo plugin `scripts/export_bundle.py`",
        "",
        "---",
        "",
        "## Índice",
        "",
        "1. [Visão Geral](#visão-geral)",
        "2. [Stack Tecnológica](#stack-tecnológica)",
        "3. [Arquitetura do Sistema](#arquitetura-do-sistema)",
        "4. [Agente de Ads (LangGraph)](#agente-de-ads-langgraph)",
        "5. [Agente de Email (Brevo)](#agente-de-email-brevo)",
        "6. [API FastAPI](#api-fastapi)",
        "7. [Banco de Dados (Supabase)](#banco-de-dados-supabase)",
        "8. [Aprovação Humana e WhatsApp](#aprovação-humana-e-whatsapp)",
        "9. [Kill Switch](#kill-switch)",
        "10. [Deploy e Infraestrutura](#deploy-e-infraestrutura)",
        "11. [Variáveis de Ambiente](#variáveis-de-ambiente)",
        "12. [Setup e Execução](#setup-e-execução)",
        "13. [Inventário de Arquivos](#inventário-de-arquivos)",
        "",
        "---",
        "",
        "## Visão Geral",
        "",
        "O **Veltrus Ads Agent** é um sistema multi-agente autônomo que monitora,",
        "analisa e otimiza campanhas de anúncios em **Meta Ads** e **Google Ads**.",
        "Inclui também um agente de **email marketing** integrado ao **Brevo**.",
        "",
        "### Funcionalidades implementadas",
        "",
        "| Feature | Status | Arquivo principal |",
        "|---------|--------|-------------------|",
        "| Agente de Ads (LangGraph) | ✅ Implementado | `agent/graph.py` |",
        "| Agente de Email (Brevo) | ✅ Implementado | `agent/email_graph.py` |",
        "| API de decisões (aprovação humana) | ✅ Implementado | `api/routers/decisions.py` |",
        "| Trigger manual do agente | ✅ Implementado | `api/routers/run.py` |",
        "| Trigger email marketing | ✅ Implementado | `api/routers/run_email.py` |",
        "| Integração Meta Ads API | ✅ Implementado | `agent/tools/meta_ads.py` |",
        "| Integração Google Ads API | ✅ Implementado | `agent/tools/google_ads.py` |",
        "| Integração Brevo API | ✅ Implementado | `agent/tools/email_brevo.py` |",
        "| Memória persistente (Supabase) | ✅ Implementado | `agent/tools/supabase_client.py` |",
        "| Normalizador de métricas | ✅ Implementado | `agent/tools/normalizer.py` |",
        "| Kill Switch (proteção financeira) | ✅ Implementado | `scripts/kill_switch.py` |",
        "| Agendamento APScheduler | ✅ Implementado | `agent/main.py` |",
        "| Docker Compose (api + agent + caddy) | ✅ Implementado | `docker-compose.yml` |",
        "| Notificação n8n/WhatsApp | ✅ Implementado | `agent/graph.py` → `notify_human` |",
        "| Dashboard Next.js | 🔶 Scaffold | `dashboard/` |",
        "",
    ]

    if git:
        lines += [
            "### Versão exportada",
            "",
            f"- **Commit:** `{git.get('commit', 'N/A')}`",
            f"- **Branch:** `{git.get('branch', 'N/A')}`",
            f"- **Data:** {git.get('date', 'N/A')}",
            f"- **Mensagem:** {git.get('message', 'N/A')}",
            "",
        ]

    lines += [
        "---",
        "",
        "## Stack Tecnológica",
        "",
        "| Camada | Tecnologia | Versão/Ferramenta |",
        "|--------|------------|-------------------|",
        "| Agente | Python + LangGraph | Python 3.12 |",
        "| LLM | Anthropic Claude | claude-sonnet-4-6 |",
        "| API | FastAPI + Uvicorn | REST |",
        "| Banco | Supabase (Postgres) | pgvector |",
        "| Frontend | Next.js 14 + Tailwind | App Router |",
        "| Agendamento | APScheduler | BlockingScheduler |",
        "| Deploy | Docker + Caddy | TLS automático |",
        "| Email | Brevo API v3 | REST |",
        "",
        "---",
        "",
        "## Arquitetura do Sistema",
        "",
        "```",
        "┌─────────────────────────────────────────────────────────────┐",
        "│                    Dashboard (Next.js)                      │",
        "│              Visualização · Configuração · Alertas          │",
        "└───────────────────────────┬─────────────────────────────────┘",
        "                            │ HTTP",
        "┌───────────────────────────▼─────────────────────────────────┐",
        "│                        API (FastAPI)                        │",
        "│     /decisions · /run · /run-email · /health                │",
        "└───────────────────────────┬─────────────────────────────────┘",
        "                            │",
        "┌───────────────────────────▼─────────────────────────────────┐",
        "│                   Agente (LangGraph)                        │",
        "│  Ads Graph: analista → estrategista → revisor → executor    │",
        "│  Email Graph: pesquisador → copywriter → executor → ...     │",
        "└───────┬───────────────────────┬─────────────────────────────┘",
        "        │                       │",
        "┌───────▼──────┐    ┌───────────▼──────────────────────────┐",
        "│  Supabase    │    │         APIs Externas                 │",
        "│  · Database  │    │  · Meta Marketing API                 │",
        "│  · Memória   │    │  · Google Ads API                    │",
        "│  · Decisões  │    │  · Anthropic API (Claude)            │",
        "└──────────────┘    │  · Brevo API (email)                 │",
        "                    └──────────────────────────────────────┘",
        "```",
        "",
        "---",
        "",
        "## Agente de Ads (LangGraph)",
        "",
        "**Arquivo:** `agent/graph.py`",
        "",
        "### Fluxo do grafo",
        "",
        "```",
        "START → analista ─(anomalias?)→ estrategista → revisor → executor → memorizador → END",
        "                └─(sem anomalias)──────────────────────────────→ memorizador → END",
        "```",
        "",
        "### Nós",
        "",
        "| Nó | Função |",
        "|----|--------|",
        "| `analista` | Busca métricas 7 dias, detecta anomalias (CPA spike, ROAS < 1, CTR drop) |",
        "| `estrategista` | Define ação: budget_increase/decrease, pause/activate, monitor_only |",
        "| `revisor` | Classifica risco: LOW / MEDIUM / HIGH |",
        "| `executor` | Salva decisão, executa via API ou enfileira aprovação humana |",
        "| `memorizador` | Grava 1-3 insights em `agent_memory` |",
        "",
        "### Ferramentas (tools)",
        "",
        "| Tool | Descrição |",
        "|------|-----------|",
        "| `fetch_account_campaigns` | Campanhas do Supabase |",
        "| `fetch_daily_metrics` | Métricas normalizadas |",
        "| `fetch_meta_campaigns_live` | Campanhas Meta em tempo real |",
        "| `fetch_meta_insights_live` | Insights Meta em tempo real |",
        "| `search_agent_memory` | Busca textual em memória |",
        "| `save_decision` | Insere em `agent_decisions` |",
        "| `run_meta_action` | pause / activate / budget via Meta |",
        "| `run_google_action` | pause / activate / budget via Google |",
        "| `notify_human` | POST para n8n webhook |",
        "| `save_memory` | Insere em `agent_memory` |",
        "",
        "### Regras de execução",
        "",
        "| Risco | AGENT_AUTONOMOUS_MODE=true | AGENT_AUTONOMOUS_MODE=false |",
        "|-------|---------------------------|----------------------------|",
        "| LOW | Executa automaticamente | Enfileira aprovação humana |",
        "| MEDIUM | Enfileira aprovação humana | Enfileira aprovação humana |",
        "| HIGH | Enfileira aprovação humana | Enfileira aprovação humana |",
        "",
        "### Entrypoints",
        "",
        "| Arquivo | Função |",
        "|---------|--------|",
        "| `agent/run.py` | `run_all_accounts()` — executa grafo para cada conta ativa |",
        "| `agent/main.py` | APScheduler — ciclo a cada `AGENT_CYCLE_INTERVAL_MINUTES` |",
        "",
        "---",
        "",
        "## Agente de Email (Brevo)",
        "",
        "**Arquivo:** `agent/email_graph.py`",
        "",
        "### Fluxo do grafo",
        "",
        "```",
        "START → pesquisador → analista_de_lista → copywriter → otimizador",
        "      → executor → analista_de_resultados → END",
        "```",
        "",
        "### Nós",
        "",
        "| Nó | Função |",
        "|----|--------|",
        "| `pesquisador` | Web search (Anthropic) para mercado/concorrentes/tendências |",
        "| `analista_de_lista` | Listas Brevo, campanhas recentes, melhor horário |",
        "| `copywriter` | 3 variantes de assunto + corpo HTML |",
        "| `otimizador` | Calcula `scheduled_at` (ISO UTC) |",
        "| `executor` | Cria campanha Brevo + upsert `email_campaigns` |",
        "| `analista_de_resultados` | Busca relatório, atualiza DB, salva memórias |",
        "",
        "### Trigger via API",
        "",
        "```bash",
        "curl -X POST http://localhost:8000/run-email \\",
        "  -H \"X-API-Key: $API_SECRET_KEY\" \\",
        "  -H \"Content-Type: application/json\" \\",
        "  -d '{\"client_id\": \"uuid\", \"list_id\": 1, \"context\": \"Black Friday\"}'",
        "```",
        "",
        "---",
        "",
        "## API FastAPI",
        "",
        "**Arquivo:** `api/main.py`",
        "",
        "### Endpoints implementados",
        "",
        "| Método | Path | Auth | Descrição |",
        "|--------|------|------|-----------|",
        "| `GET` | `/health` | — | Health check |",
        "| `GET` | `/decisions` | X-API-Key | Lista decisões pendentes |",
        "| `PATCH` | `/decisions/{id}/approve` | X-API-Key | Aprova e executa ação |",
        "| `PATCH` | `/decisions/{id}/reject` | X-API-Key | Rejeita com motivo |",
        "| `POST` | `/run` | X-API-Key | Dispara ciclo do agente em background |",
        "| `POST` | `/run-email` | X-API-Key | Dispara agente de email em background |",
        "",
        "### Autenticação",
        "",
        "Todos os endpoints (exceto `/health`) requerem header:",
        "```",
        "X-API-Key: {API_SECRET_KEY}",
        "```",
        "",
        "### Documentação interativa",
        "",
        "- Swagger UI: `http://localhost:8000/docs`",
        "- ReDoc: `http://localhost:8000/redoc`",
        "",
        "---",
        "",
        "## Banco de Dados (Supabase)",
        "",
        "### Migrations",
        "",
        "| Arquivo | Conteúdo |",
        "|---------|----------|",
        "| `001_initial_schema.sql` | clients, ad_accounts, campaigns, daily_metrics, agent_decisions, agent_memory |",
        "| `002_add_normalized_fields.sql` | attribution_window, confidence_score em daily_metrics |",
        "| `003_kill_switch_log.sql` | Tabela kill_switch_log (auditoria) |",
        "| `004_email_campaigns.sql` | Tabela email_campaigns (Brevo) |",
        "",
        "### Tabelas principais",
        "",
        "| Tabela | Propósito |",
        "|--------|-----------|",
        "| `clients` | Clientes Veltrus (name, vertical, business_dna) |",
        "| `ad_accounts` | Contas Meta/Google vinculadas |",
        "| `campaigns` | Campanhas monitoradas |",
        "| `daily_metrics` | Métricas diárias (spend, cpa, roas, ctr) |",
        "| `agent_decisions` | Decisões do agente (ação, reasoning, executed) |",
        "| `agent_memory` | Memória persistente (content, embedding vector) |",
        "| `kill_switch_log` | Log do kill switch |",
        "| `email_campaigns` | Campanhas de email (Brevo) |",
        "",
        "---",
        "",
        "## Aprovação Humana e WhatsApp",
        "",
        "### Fluxo completo",
        "",
        "```",
        "Agente LangGraph",
        "  └─ executor (risco MEDIUM/HIGH ou autonomous=false)",
        "       └─ save_decision(executed=false)",
        "       └─ notify_human()",
        "            └─ POST → N8N_WEBHOOK_URL",
        "                     │",
        "               ┌─────▼─────────────────────────────┐",
        "               │  n8n Workflow                        │",
        "               │  1. Webhook (trigger)                │",
        "               │  2. WhatsApp Business API (botões)   │",
        "               │  3. Webhook (resposta do usuário)    │",
        "               │  4. PATCH /decisions/{id}/approve    │",
        "               │     ou /decisions/{id}/reject        │",
        "               └─────────────────────────────────────┘",
        "```",
        "",
        "### Payload enviado ao n8n",
        "",
        "```json",
        "{",
        '  "decision_id": "uuid",',
        '  "campaign_name": "Campanha Black Friday",',
        '  "action_type": "budget_increase",',
        '  "risk_level": "MEDIUM",',
        '  "reasoning": "ROAS 3.8x acima da meta...",',
        '  "phone_number": "5511999998888"',
        "}",
        "```",
        "",
        "### Estados de uma decisão",
        "",
        "| executed | approved_at | Significado |",
        "|----------|-------------|-------------|",
        "| false | null | ⏳ Pendente |",
        "| true | preenchido | ✅ Aprovada e executada |",
        "| false | preenchido | ❌ Rejeitada |",
        "",
        "---",
        "",
        "## Kill Switch",
        "",
        "**Arquivo:** `scripts/kill_switch.py`",
        "",
        "Script de segurança **independente do agente** — roda via cron a cada hora.",
        "",
        "| Regra | Condição | Ação |",
        "|-------|----------|------|",
        "| `spend_overage` | gasto hoje > daily_budget × 1.1 | Pausa campanha |",
        "| `cpa_spike` | CPA hoje > cpa_max × 2.0 | Pausa campanha |",
        "| `roas_critical` | ROAS hoje < 0.5 | Alerta (sem pausa) |",
        "",
        "```bash",
        "# Execução manual",
        "PYTHONPATH=. python scripts/kill_switch.py",
        "",
        "# Simulação (dry-run)",
        "PYTHONPATH=. python scripts/kill_switch.py --dry-run",
        "```",
        "",
        "---",
        "",
        "## Deploy e Infraestrutura",
        "",
        "### Docker Compose",
        "",
        "| Serviço | Comando | Porta |",
        "|---------|---------|-------|",
        "| `api` | uvicorn api.main:app --workers 2 | 8000 (interno) |",
        "| `agent` | python -m agent.main | — |",
        "| `caddy` | Reverse proxy + TLS | 80, 443 |",
        "",
        "### Scripts de deploy",
        "",
        "| Script | Função |",
        "|--------|--------|",
        "| `scripts/setup.sh` | Bootstrap VPS (Docker, compose) |",
        "| `scripts/deploy.sh` | git pull + docker compose up |",
        "| `scripts/remote_deploy.sh` | rsync + SSH deploy |",
        "| `scripts/seed_test_data.py` | Dados de teste para dev |",
        "",
        "### Railway",
        "",
        "- `Procfile` — uvicorn na porta `$PORT`",
        "- `railway.json` — Nixpacks build, healthcheck `/health`",
        "",
        "---",
        "",
        "## Variáveis de Ambiente",
        "",
        "Veja `.env.example` para a lista completa. Principais:",
        "",
        "| Variável | Obrigatória | Descrição |",
        "|----------|-------------|-----------|",
        "| `ANTHROPIC_API_KEY` | ✅ | Chave da API Anthropic |",
        "| `SUPABASE_URL` | ✅ | URL do projeto Supabase |",
        "| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Chave service_role |",
        "| `API_SECRET_KEY` | ✅ | Chave de autenticação da API |",
        "| `META_ACCESS_TOKEN` | — | Token Meta Ads |",
        "| `GOOGLE_ADS_*` | — | Credenciais Google Ads |",
        "| `BREVO_API_KEY` | — | Chave Brevo (email) |",
        "| `AGENT_AUTONOMOUS_MODE` | — | false = somente leitura (padrão) |",
        "| `N8N_WEBHOOK_URL` | — | Webhook n8n para WhatsApp |",
        "",
        "---",
        "",
        "## Setup e Execução",
        "",
        "```bash",
        "# 1. Configurar ambiente",
        "cp .env.example .env",
        "# Preencher todas as variáveis",
        "",
        "# 2. Backend Python",
        "python -m venv venv && source venv/bin/activate",
        "pip install -r requirements.txt",
        "",
        "# 3. Aplicar migrations no Supabase",
        "# (via Supabase CLI ou dashboard SQL editor)",
        "",
        "# 4. Iniciar API",
        "PYTHONPATH=. uvicorn api.main:app --reload --port 8000",
        "",
        "# 5. Iniciar agente (ciclo agendado)",
        "PYTHONPATH=. python -m agent.main",
        "",
        "# 6. Ou disparar manualmente",
        "curl -X POST http://localhost:8000/run -H \"X-API-Key: $API_SECRET_KEY\"",
        "```",
        "",
        "---",
        "",
        "## Inventário de Arquivos",
        "",
        f"Total de arquivos no pacote: **{len(files)}**",
        f"Arquivos Python com código: **{len(py_files)}**",
        f"Migrations SQL: **{len(sql_files)}**",
        "",
        "### Estrutura de pastas",
        "",
        "```",
    ]

    # Build tree
    tree: dict[str, list[str]] = {}
    for f in files:
        rel = str(f.relative_to(ROOT))
        parts = rel.split("/")
        if len(parts) == 1:
            tree.setdefault(".", []).append(rel)
        else:
            tree.setdefault(parts[0], []).append(rel)

    for folder in sorted(tree.keys()):
        lines.append(f"{folder}/")
        for item in sorted(tree[folder])[:30]:
            if item != f"{folder}/":
                fname = item.split("/")[-1] if "/" in item else item
                fpath = ROOT / item
                size = fpath.stat().st_size if fpath.exists() else 0
                nlines = _count_lines(fpath) if fpath.suffix == ".py" else 0
                extra = f" ({nlines} linhas)" if nlines else ""
                lines.append(f"  ├── {fname} ({size:,} bytes{extra})")
        if len(tree[folder]) > 30:
            lines.append(f"  └── ... +{len(tree[folder]) - 30} arquivos")
    lines.append("```")
    lines.append("")

    # Manifest table
    lines += [
        "### Manifesto completo",
        "",
        "| Arquivo | Tamanho | SHA256 (16) |",
        "|---------|---------|-------------|",
    ]
    for f in files:
        rel = str(f.relative_to(ROOT))
        size = f.stat().st_size
        digest = _sha256(f)
        lines.append(f"| `{rel}` | {size:,} | `{digest}` |")

    lines += [
        "",
        "---",
        "",
        "*Documentação gerada pelo plugin `scripts/export_bundle.py` — Veltrus Ads Agent*",
    ]

    return "\n".join(lines)


def create_bundle(output_path: Path, files: list[Path], docs: str) -> dict:
    """Cria o arquivo ZIP com todos os arquivos e documentação."""
    manifest: list[dict] = []

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Documentação gerada
        zf.writestr("docs/PROJETO_COMPLETO.md", docs)

        for f in files:
            rel = f.relative_to(ROOT)
            zf.write(f, rel)
            manifest.append({
                "path": str(rel),
                "size": f.stat().st_size,
                "sha256": _sha256(f),
            })

        # Manifesto JSON
        git = _git_info()
        bundle_meta = {
            "project": "veltrus-ads-agent",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git": git,
            "file_count": len(manifest) + 1,
            "files": manifest,
        }
        zf.writestr("MANIFEST.json", json.dumps(bundle_meta, indent=2, ensure_ascii=False))

    return bundle_meta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Veltrus Ads Agent — Exporta pacote completo do projeto",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Caminho do arquivo ZIP de saída (padrão: dist/veltrus-ads-agent-{timestamp}.zip)",
    )
    parser.add_argument(
        "--docs-only",
        action="store_true",
        help="Gera apenas a documentação (docs/PROJETO_COMPLETO.md), sem ZIP",
    )
    args = parser.parse_args()

    print("🔍 Coletando arquivos do projeto...")
    files = _collect_files()
    print(f"   {len(files)} arquivos encontrados")

    print("📝 Gerando documentação completa...")
    docs = generate_documentation(files)

    docs_path = ROOT / "docs" / "PROJETO_COMPLETO.md"
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(docs, encoding="utf-8")
    print(f"   Documentação salva em: {docs_path.relative_to(ROOT)}")

    if args.docs_only:
        print("✅ Documentação gerada (modo --docs-only, ZIP não criado)")
        return 0

    DIST.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or DIST / f"veltrus-ads-agent-{timestamp}.zip"

    print(f"📦 Criando pacote ZIP: {output.name}...")
    meta = create_bundle(output, files, docs)

    size_mb = output.stat().st_size / (1024 * 1024)
    print("")
    print("=" * 60)
    print("✅ PACOTE EXPORTADO COM SUCESSO")
    print("=" * 60)
    print(f"   Arquivo:  {output}")
    print(f"   Tamanho:  {size_mb:.2f} MB")
    print(f"   Arquivos: {meta['file_count']}")
    if meta.get("git", {}).get("commit"):
        print(f"   Commit:   {meta['git']['commit'][:12]}")
    print("")
    print("Conteúdo do pacote:")
    print("   • Código-fonte completo (agent, api, dashboard, scripts)")
    print("   • Migrations Supabase (4 arquivos SQL)")
    print("   • Configuração Docker (Dockerfile, docker-compose, Caddyfile)")
    print("   • docs/PROJETO_COMPLETO.md — documentação detalhada")
    print("   • MANIFEST.json — inventário com checksums")
    print("")
    print(f"Para baixar: copie o arquivo de {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
