#!/usr/bin/env python3
"""
scripts/export_project.py — Exporta o projeto completo como ZIP (uso local)

Uso:
    python scripts/export_project.py
    python scripts/export_project.py --output /tmp/meu-export.zip
    python scripts/export_project.py --no-docs

Saída padrão: ./veltrus-ads-agent_YYYYMMDD_HHMMSS.zip
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Padrões de exclusão
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
}

_EXCLUDE_FILES = {
    ".env",
    ".env.local",
    ".env.production",
}

_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB


def _should_include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    for part in rel.parts[:-1]:
        if part in _EXCLUDE_DIRS or part.endswith(".egg-info"):
            return False
    if path.name in _EXCLUDE_FILES:
        return False
    if path.suffix in _EXCLUDE_EXTENSIONS:
        return False
    if path.stat().st_size > _MAX_FILE_BYTES:
        return False
    return True


def _collect_files(root: Path) -> list[Path]:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and _should_include(p, root):
            files.append(p)
    return files


def _build_documentation(root: Path, collected: list[Path]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    file_list = "\n".join(f"- `{p.relative_to(root)}`" for p in collected)

    return f"""# Veltrus Ads Agent — Documentação Completa

> Gerado em {now}

---

## 1. Visão Geral

**Veltrus Ads Agent** é um sistema autônomo de gestão de campanhas (Meta Ads + Google Ads)
com email marketing (Brevo). Usa LangGraph + Claude para otimizações automáticas com
controle humano via API.

---

## 2. Stack

| Camada | Tecnologia |
|--------|-----------|
| Agente | Python 3.12 · LangGraph · LangChain Anthropic |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) |
| API | FastAPI · Uvicorn |
| Banco | Supabase (PostgreSQL + pgvector) |
| Meta Ads | `facebook-business` SDK |
| Google Ads | `google-ads` SDK |
| Email | Brevo REST API |
| Scheduler | APScheduler |
| Deploy | Docker · Docker Compose · Railway |

---

## 3. Ads Graph (5 nós)

```
START → analista ──(anomalias)──→ estrategista → revisor → executor → memorizador → END
                └──(sem anomalias)────────────────────────────────→ memorizador → END
```

| Nó | Função |
|----|--------|
| analista | Coleta métricas 7d, detecta cpa_spike / roas_negative / ctr_drop |
| estrategista | Decide ação (budget_increase/decrease, pause, monitor) via memória |
| revisor | Classifica risco: LOW / MEDIUM / HIGH |
| executor | Executa via API ou enfileira para aprovação humana |
| memorizador | Persiste aprendizados em agent_memory |

---

## 4. Email Graph (6 nós)

```
pesquisador → analista_de_lista → copywriter → otimizador → executor → analista_de_resultados
```

---

## 5. API Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| GET | /health | Status |
| GET | /decisions | Decisões pendentes |
| PATCH | /decisions/{{id}}/approve | Aprovar + executar |
| PATCH | /decisions/{{id}}/reject | Rejeitar |
| POST | /run | Disparar ciclo de ads |
| POST | /run-email | Disparar ciclo de email |
| GET | /download/project | Download ZIP do projeto |
| GET | /download/manifest | Manifesto de arquivos |

Autenticação: `X-API-Key: <API_SECRET_KEY>`

---

## 6. Schema do Banco

| Tabela | Descrição |
|--------|-----------|
| clients | Clientes com business_dna JSONB |
| ad_accounts | Contas Meta/Google com token |
| campaigns | Campanhas monitoradas |
| daily_metrics | Métricas diárias normalizadas + raw_payload |
| agent_decisions | Histórico de decisões com raciocínio |
| agent_memory | Memória semântica pgvector (1536d) |
| kill_switch_log | Auditoria de ações de emergência |
| email_campaigns | Campanhas Brevo com métricas |

---

## 7. Arquivos Incluídos

{file_list}

---

*Gerado por scripts/export_project.py — Veltrus Ads Agent v0.1.0*
"""


def create_zip(
    root: Path,
    output_path: Path,
    include_docs: bool = True,
    verbose: bool = True,
) -> Path:
    """Cria o ZIP do projeto e retorna o caminho do arquivo gerado."""
    collected = _collect_files(root)

    if verbose:
        print(f"[export] Raiz: {root}")
        print(f"[export] Arquivos coletados: {len(collected)}")

    zip_buffer = io.BytesIO()
    skipped = 0

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in collected:
            archive_name = str(file_path.relative_to(root))
            try:
                zf.write(file_path, arcname=archive_name)
                if verbose:
                    size_kb = file_path.stat().st_size / 1024
                    print(f"  + {archive_name} ({size_kb:.1f} KB)")
            except Exception as exc:
                print(f"  ! SKIP {archive_name}: {exc}", file=sys.stderr)
                skipped += 1
                continue

        if include_docs:
            doc_content = _build_documentation(root, collected)
            zf.writestr("DOCUMENTACAO.md", doc_content.encode("utf-8"))
            if verbose:
                print(f"  + DOCUMENTACAO.md (gerado)")

        manifest_lines = [
            f"# Export Manifest — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"# Total: {len(collected)} arquivos",
            "",
        ] + [str(p.relative_to(root)) for p in collected]
        if include_docs:
            manifest_lines.append("DOCUMENTACAO.md")
        zf.writestr("EXPORT_MANIFEST.txt", "\n".join(manifest_lines))

    # Grava no disco
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(zip_buffer.getvalue())

    zip_size_kb = output_path.stat().st_size / 1024
    if verbose:
        print(f"\n[export] ZIP gerado: {output_path}")
        print(f"[export] Tamanho: {zip_size_kb:.1f} KB")
        if skipped:
            print(f"[export] Arquivos pulados: {skipped}")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exporta o projeto Veltrus Ads Agent como ZIP."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Caminho de saída do ZIP (padrão: ./veltrus-ads-agent_TIMESTAMP.zip)",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Não incluir DOCUMENTACAO.md gerado",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suprimir saída verbose",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent  # /workspace

    if args.output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output = root / f"veltrus-ads-agent_{timestamp}.zip"

    create_zip(
        root=root,
        output_path=args.output,
        include_docs=not args.no_docs,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
