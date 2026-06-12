#!/usr/bin/env bash
# =============================================================================
# setup.sh — Configuração inicial do VPS para Veltrus Ads Agent
# Executar como root no VPS: bash setup.sh
# =============================================================================
set -euo pipefail

DEPLOY_DIR="/opt/veltrus"
REPO_URL="${REPO_URL:-https://github.com/$(git remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]\(.*\)\.git|\1|')}"

echo "=== Veltrus VPS Setup ==="

# Docker
if ! command -v docker &>/dev/null; then
    echo "[1/4] Instalando Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "[1/4] Docker já instalado: $(docker --version)"
fi

# Docker Compose plugin
if ! docker compose version &>/dev/null; then
    echo "[2/4] Instalando Docker Compose plugin..."
    apt-get update -qq && apt-get install -y docker-compose-plugin
else
    echo "[2/4] Docker Compose já disponível: $(docker compose version)"
fi

# Diretório de deploy
echo "[3/4] Preparando ${DEPLOY_DIR}..."
mkdir -p "${DEPLOY_DIR}"

# .env já deve estar em ${DEPLOY_DIR}/.env — verificar
if [[ ! -f "${DEPLOY_DIR}/.env" ]]; then
    echo "ERRO: ${DEPLOY_DIR}/.env não encontrado."
    echo "Copie o .env para ${DEPLOY_DIR}/.env antes de continuar."
    exit 1
fi

# Verificar Anthropic API key
if grep -q "sk-ant-PREENCHA_AQUI" "${DEPLOY_DIR}/.env"; then
    echo "AVISO: ANTHROPIC_API_KEY ainda tem placeholder. Atualize antes de continuar."
    echo "  sed -i 's|sk-ant-PREENCHA_AQUI|SUA_CHAVE_REAL|' ${DEPLOY_DIR}/.env"
    exit 1
fi

echo "[4/4] Setup concluído. Execute deploy.sh para subir os containers."
