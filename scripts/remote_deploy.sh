#!/usr/bin/env bash
# =============================================================================
# remote_deploy.sh — Deploy remoto via SSH no VPS Hostinger
# Uso: VPS_HOST=76.13.232.175 VPS_KEY=/path/to/key bash remote_deploy.sh
#
# Requer variáveis de ambiente:
#   VPS_HOST        — IP do VPS (padrão: 76.13.232.175)
#   VPS_USER        — usuário SSH (padrão: root)
#   VPS_KEY         — caminho da chave SSH privada (opcional se já no ssh-agent)
#   ANTHROPIC_KEY   — Anthropic API key real (sk-ant-...)
# =============================================================================
set -euo pipefail

VPS_HOST="${VPS_HOST:-76.13.232.175}"
VPS_USER="${VPS_USER:-root}"
VPS_KEY="${VPS_KEY:-}"
DEPLOY_DIR="/opt/veltrus"

if [[ -z "${ANTHROPIC_KEY:-}" ]]; then
    echo "ERRO: variável ANTHROPIC_KEY não definida."
    echo "Uso: ANTHROPIC_KEY=sk-ant-... bash remote_deploy.sh"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"
if [[ -n "${VPS_KEY}" ]]; then
    SSH_OPTS="${SSH_OPTS} -i ${VPS_KEY}"
fi

echo "=== Remote Deploy — ${VPS_USER}@${VPS_HOST}:${DEPLOY_DIR} ==="

# 1. Criar diretório de deploy
echo "[1/5] Criando diretório ${DEPLOY_DIR}..."
ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "mkdir -p ${DEPLOY_DIR}"

# 2. Upload dos arquivos do projeto
echo "[2/5] Enviando código fonte..."
rsync -az --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='dashboard/node_modules' \
    --exclude='dashboard/.next' \
    --exclude='tests' \
    ${VPS_KEY:+-e "ssh -i ${VPS_KEY} -o StrictHostKeyChecking=no"} \
    ./ "${VPS_USER}@${VPS_HOST}:${DEPLOY_DIR}/"

# 3. Atualizar Anthropic API key no .env
echo "[3/5] Atualizando ANTHROPIC_API_KEY no .env..."
ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" \
    "sed -i 's|sk-ant-PREENCHA_AQUI|${ANTHROPIC_KEY}|g' ${DEPLOY_DIR}/.env && \
     grep -q 'ANTHROPIC_API_KEY=sk-ant-' ${DEPLOY_DIR}/.env && echo 'API key atualizada OK'"

# 4. Garantir Docker instalado e executar deploy
echo "[4/5] Executando deploy no VPS..."
ssh ${SSH_OPTS} "${VPS_USER}@${VPS_HOST}" "bash ${DEPLOY_DIR}/scripts/setup.sh && bash ${DEPLOY_DIR}/scripts/deploy.sh --build"

# 5. Health check externo
echo "[5/5] Health check externo..."
sleep 10
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://veltrus-api.ehos.com.br/health 2>/dev/null || echo "000")
if [[ "${HTTP_CODE}" == "200" ]]; then
    echo "✓ https://veltrus-api.ehos.com.br/health — HTTP 200 OK"
else
    echo "⚠ https://veltrus-api.ehos.com.br/health — HTTP ${HTTP_CODE} (TLS pode demorar ~30s)"
    echo "Tente em 1 minuto: curl https://veltrus-api.ehos.com.br/health"
fi

echo ""
echo "=== Remote deploy concluído ==="
