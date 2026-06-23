#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Deploy/redeploy do Veltrus Ads Agent no VPS
# Uso: bash deploy.sh [--build]
# =============================================================================
set -euo pipefail

DEPLOY_DIR="/opt/veltrus"
BUILD_FLAG=""

if [[ "${1:-}" == "--build" ]]; then
    BUILD_FLAG="--build"
fi

echo "=== Veltrus Deploy ==="
echo "Dir: ${DEPLOY_DIR}"
echo "Build: ${BUILD_FLAG:-no}"

cd "${DEPLOY_DIR}"

if [[ -d ".git" ]]; then
    echo "[git] Atualizando código..."
    git pull --ff-only origin main
fi

echo "[docker] Subindo serviços: api, agent, caddy"
docker compose up -d ${BUILD_FLAG} --remove-orphans api agent caddy

echo ""
echo "=== Status dos containers ==="
docker compose ps

echo ""
echo "=== Health check ==="
sleep 5
MAX_TRIES=12
for i in $(seq 1 ${MAX_TRIES}); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
    if [[ "${HTTP_CODE}" == "200" ]]; then
        echo "✓ /health OK (HTTP 200)"
        break
    fi
    if [[ "${i}" == "${MAX_TRIES}" ]]; then
        echo "✗ /health não respondeu após ${MAX_TRIES} tentativas"
        echo "Logs da API:"
        docker compose logs --tail=50 api
        exit 1
    fi
    echo "  tentativa ${i}/${MAX_TRIES}: HTTP ${HTTP_CODE} — aguardando..."
    sleep 5
done

echo ""
echo "=== Deploy concluído ==="
echo "API local:   http://localhost:8000/health"
echo "API pública: https://veltrus-api.ehos.com.br/health"
