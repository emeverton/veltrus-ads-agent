#!/usr/bin/env bash
# Veltrus Ads Agent — setup no VPS Hostinger
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/veltrus}"
REPO_URL="${REPO_URL:-https://github.com/emeverton/veltrus-ads-agent.git}"
BRANCH="${BRANCH:-main}"

log() { printf '[veltrus-setup] %s\n' "$*"; }

if ! command -v docker >/dev/null 2>&1; then
  log "Docker não encontrado. Instale Docker Engine antes de continuar."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  log "Docker Compose plugin não encontrado."
  exit 1
fi

mkdir -p "$APP_DIR"
cd "$APP_DIR"

if [ ! -f .env ]; then
  log "Arquivo .env ausente em $APP_DIR — copie de .env.example e preencha."
  exit 1
fi

if grep -q 'sk-ant-PREENCHA_AQUI' .env 2>/dev/null; then
  log "ERRO: substitua sk-ant-PREENCHA_AQUI no .env pela ANTHROPIC_API_KEY real."
  exit 1
fi

if [ ! -f docker-compose.yml ]; then
  log "Clonando repositório em $APP_DIR..."
  if [ -d .git ]; then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
  else
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" /tmp/veltrus-src
    rsync -a --exclude .git /tmp/veltrus-src/ "$APP_DIR/"
    rm -rf /tmp/veltrus-src
  fi
fi

log "Subindo stack (api, agent, worker, beat, redis)..."
docker compose up -d --build

log "Aguardando API..."
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    log "API OK em http://127.0.0.1:8000/health"
    break
  fi
  sleep 2
done

if [ -f Caddyfile ] && command -v caddy >/dev/null 2>&1; then
  log "Recarregando Caddy..."
  caddy validate --config Caddyfile
  caddy reload --config Caddyfile || caddy run --config Caddyfile &
fi

docker compose ps
log "Deploy concluído."
